"""Focused tests for the Section Learning feature.

Scope is limited to Section Learning: heading detection, concept normalization,
whole-paper coverage in the prompt, generation/persistence behaviour, and the
guard against fabricated sections.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Paper, PaperContent, PaperSection
from .prompts.section_learning import build_section_learning_prompt
from .section_learning_service import (
    SECTION_LEARNING_COMPLETION_TOKENS,
    SECTION_LEARNING_MAX_SECTIONS,
    SectionLearningError,
    generate_section_learning,
)
from .section_normalizer import (
    build_structure_digest,
    classify_heading,
    detect_paper_structure,
    display_section_title,
    is_excluded_heading,
    looks_like_heading_text,
    looks_like_section_heading,
    normalize_section_title,
    split_paper_blocks,
)

STANDARD_PAPER_TEXT = """Abstract
This paper proposes a hybrid citation recommendation model and reports consistent gains on three scholarly datasets.

1. Introduction
Scholarly search suffers from sparse metadata, so we motivate a hybrid ranking design for citation recommendation.

2. Related Work
Earlier ranking systems relied on TF-IDF and BM25, while more recent systems used dense retrieval encoders.

3. Methodology
We combine a dense text encoder with a citation graph propagation layer trained using a contrastive objective.

4. Results
The hybrid model reaches 0.71 nDCG@10 and improves over the BM25 baseline by 12.4 percent on the held out split.

5. Conclusion
The hybrid design is effective and future work will extend the study to multilingual collections.

References
[1] A prior study on ranking.
"""

VARIANT_PAPER_TEXT = """Abstract
This study evaluates three optimizers for medical image segmentation on a public benchmark.

I. Introduction
Segmentation quality depends heavily on optimizer choice, which motivates a controlled comparison.

II. Background
Previous segmentation systems used hand tuned learning rate schedules and reported unstable convergence.

III. Proposed Approach
Our proposed approach trains an encoder decoder network with adaptive optimization and cosine decay.

IV. Experimental Results
The adaptive optimizer reaches a Dice score of 0.884, outperforming the momentum baseline by 3.1 points.

V. Conclusions and Future Work
Adaptive optimization is preferable for this task and future work covers three dimensional volumes.

Acknowledgements
We thank the reviewers.
"""

NO_RELATED_WORK_PAPER_TEXT = """Abstract
This report describes a deployment study of an on device inference runtime.

1. Introduction
Edge deployment is constrained by memory, which motivates the runtime described here.

2. Materials and Methods
The runtime was profiled on three devices using a fixed quantized model and a repeatable benchmark harness.

3. Results and Discussion
Latency dropped from 82 ms to 31 ms after operator fusion, with no measurable accuracy loss.

4. Conclusion
Operator fusion is the most effective optimization for this workload.
"""


def section_response(*titles):
    items = []
    for title in titles:
        explanation = (
            f'This section of the paper covers {title.lower()} with concrete detail drawn from the paper, '
            'including the reported setup, the measured numbers, and how the section supports the overall claim.'
        )
        items.append('{"title": "%s", "explanation": "%s"}' % (title, explanation))
    return '{"sections": [' + ', '.join(items) + ']}'


def create_paper(username, extracted_text):
    user = User.objects.create_user(username=username, password='Secret123')
    paper = Paper.objects.create(
        owner=user,
        title=f'{username} Paper',
        pdf_file=SimpleUploadedFile(f'{username}.pdf', b'%PDF-1.4\n', content_type='application/pdf'),
    )
    PaperContent.objects.create(paper=paper, extracted_text=extracted_text, extraction_status='Ready')
    return user, paper


def create_premium_subscription(user, days=7):
    from subscriptions.models import SubscriptionPlan, UserSubscription

    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='premium-weekly',
        defaults={
            'name': 'Premium Weekly',
            'description': 'Weekly premium access.',
            'price': 9.99,
            'duration_days': days,
            'is_active': True,
        },
    )
    UserSubscription.objects.create(
        user=user,
        plan=plan,
        status='ACTIVE',
        start_date=timezone.now(),
        end_date=timezone.now() + timezone.timedelta(days=days),
    )


class SectionNormalizerTests(TestCase):
    def test_major_heading_variations_are_classified(self):
        cases = {
            'Abstract': 'abstract',
            'ABSTRACT': 'abstract',
            '1. Introduction': 'introduction',
            'I. Introduction': 'introduction',
            'Related Work': 'related_work',
            'Literature Review': 'related_work',
            'Background': 'related_work',
            'Previous Work': 'related_work',
            '2 Background and Related Work': 'related_work',
            'Methodology': 'methodology',
            'Methods': 'methodology',
            'Materials and Methods': 'methodology',
            'Proposed Method': 'methodology',
            'Proposed Approach': 'methodology',
            'Experimental Setup': 'methodology',
            'System Architecture': 'methodology',
            'Implementation': 'methodology',
            'Results': 'results',
            'Results and Discussion': 'results',
            'Experiments': 'results',
            'Experimental Results': 'results',
            'Evaluation': 'results',
            'Performance Evaluation': 'results',
            'Discussion': 'results',
            'Conclusion': 'conclusion',
            'Conclusions': 'conclusion',
            'Conclusion and Future Work': 'conclusion',
            'Conclusions and Future Work': 'conclusion',
            'Summary and Conclusion': 'conclusion',
            '5. CONCLUSIONS': 'conclusion',
        }
        for heading, expected in cases.items():
            with self.subTest(heading=heading):
                self.assertEqual(classify_heading(heading), expected)

    def test_non_major_and_back_matter_headings_are_not_major_concepts(self):
        for heading in ['Dataset', 'Limitations', 'Future Work', 'References', 'Appendix A', 'Main Content']:
            with self.subTest(heading=heading):
                self.assertEqual(classify_heading(heading), '')

    def test_back_matter_headings_are_flagged_as_excluded(self):
        for heading in ['References', 'REFERENCES', 'Bibliography', 'Acknowledgements', 'Acknowledgments', 'Appendix B']:
            with self.subTest(heading=heading):
                self.assertTrue(is_excluded_heading(heading))

        for heading in ['Results', 'Methodology', 'Conclusion']:
            with self.subTest(heading=heading):
                self.assertFalse(is_excluded_heading(heading))

    def test_prose_lines_are_not_treated_as_headings(self):
        prose = [
            'The results show that the proposed method outperforms every baseline in the evaluation.',
            'In this background discussion we explain why previous work failed to scale to large corpora,',
            'we conclude that adaptive optimization is preferable for the segmentation workload studied here',
        ]
        for line in prose:
            with self.subTest(line=line):
                self.assertFalse(looks_like_section_heading(line))
                self.assertEqual(classify_heading(line), '')

    def test_normalize_section_title_ignores_numbering_and_case(self):
        self.assertEqual(normalize_section_title('4 Results'), 'results')
        self.assertEqual(normalize_section_title('RESULTS'), 'results')
        self.assertEqual(normalize_section_title('4. Results:'), 'results')
        self.assertEqual(normalize_section_title('IV. Experimental Results'), 'experimental results')

    def test_display_section_title_removes_numbering_but_keeps_wording(self):
        self.assertEqual(display_section_title('4 Results'), 'Results')
        self.assertEqual(display_section_title('4.2. Results and Discussion'), 'Results and Discussion')
        self.assertEqual(display_section_title('IV. Experimental Results'), 'Experimental Results')
        self.assertEqual(display_section_title('## Conclusion'), 'Conclusion')
        self.assertEqual(display_section_title('Materials and Methods'), 'Materials and Methods')
        self.assertEqual(display_section_title('A Survey of Ranking Models'), 'Survey of Ranking Models')
        self.assertEqual(display_section_title('Main Content'), 'Main Content')

    def test_detect_paper_structure_finds_all_major_concepts(self):
        structure = detect_paper_structure(STANDARD_PAPER_TEXT)

        self.assertTrue(structure['has_structure'])
        self.assertEqual(
            structure['concepts'],
            {'abstract', 'introduction', 'related_work', 'methodology', 'results', 'conclusion'},
        )
        self.assertNotIn('References', structure['titles'])

    def test_reported_garbage_two_column_fragments_are_never_headings(self):
        # Exact fragments reported in the bug report must never become sections.
        garbage = [
            'methods, however, were validated on relatively small private',
            'results-on the same test data-to our evaluation platform in',
            'evaluation (e.g., Menze, Geremia, Riklin Raviv).',
            'methods (Fig. 7, bottom)',
            'results are shown in Fig. 8 (labeled "Fused_4," "Fused_6,"',
            'results of updated algorithms and available test images may',
            'results submitted for the same test sets',
        ]
        for fragment in garbage:
            with self.subTest(fragment=fragment):
                self.assertFalse(looks_like_heading_text(fragment))
                self.assertFalse(looks_like_section_heading(fragment))
                self.assertEqual(classify_heading(fragment), '')

    def test_detected_headings_only_lists_real_section_headings(self):
        raw = (
            'Title\n\nAbstract\nThe abstract summarizes the work.\n\n'
            'I. INTRODUCTION\nMotivation text here.\n\n'
            'methods, however, were validated on relatively small private datasets.\n\n'
            'II. METHODS\nThe approach is described.\n\n'
            'results are shown in Fig. 8 (labeled Fused_4).\n\n'
            'III. CONCLUSION\nWe conclude.\n'
        )
        structure = detect_paper_structure(raw)
        self.assertIn('Abstract', structure['titles'])
        self.assertIn('INTRODUCTION', structure['titles'])
        self.assertIn('METHODS', structure['titles'])
        self.assertIn('CONCLUSION', structure['titles'])
        self.assertNotIn('methods, however, were validated', structure['titles'])
        self.assertNotIn('results are shown in Fig. 8', structure['titles'])

    def test_detect_paper_structure_handles_heading_variations(self):
        structure = detect_paper_structure(VARIANT_PAPER_TEXT)

        self.assertEqual(
            structure['concepts'],
            {'abstract', 'introduction', 'related_work', 'methodology', 'results', 'conclusion'},
        )
        self.assertIn('Background', structure['titles'])
        self.assertIn('Proposed Approach', structure['titles'])
        self.assertIn('Experimental Results', structure['titles'])
        self.assertIn('Conclusions and Future Work', structure['titles'])
        self.assertNotIn('Acknowledgements', structure['titles'])

    def test_paper_without_related_work_reports_missing_concept(self):
        structure = detect_paper_structure(NO_RELATED_WORK_PAPER_TEXT)

        self.assertNotIn('related_work', structure['concepts'])
        self.assertIn('methodology', structure['concepts'])
        self.assertIn('results', structure['concepts'])

    def test_structure_digest_covers_every_detected_section(self):
        digest = build_structure_digest(STANDARD_PAPER_TEXT)

        for heading in ['## Abstract', '## Introduction', '## Related Work', '## Methodology', '## Results', '## Conclusion']:
            self.assertIn(heading, digest)
        self.assertIn('0.71 nDCG@10', digest)
        self.assertIn('multilingual', digest)
        self.assertNotIn('A prior study on ranking', digest)

    def test_structure_digest_falls_back_to_head_truncation_without_headings(self):
        digest = build_structure_digest('plain body text ' * 2000, max_chars=1200)

        self.assertLessEqual(len(digest), 1220)
        self.assertIn('[truncated]', digest)

    def test_split_paper_blocks_returns_empty_without_recognizable_headings(self):
        self.assertEqual(split_paper_blocks('Just a paragraph of prose without any headings at all.'), [])

    def test_wrapped_prose_fragments_are_not_headings(self):
        # These are exactly the garbage lines reported from a two-column PDF.
        fragments = [
            'methods, however, were validated on relatively small private',
            'results-on the same test data-to our evaluation platform in',
            'methods required manual initialization.',
            'methods could not be distinguished from the "best" method',
            'evaluation tool.',
            'results submitted for the same test sets',
            'evaluation (e.g., Menze, Geremia, Riklin Raviv).',
            'methods (Fig. 7, bottom)',
            'results are shown in Fig. 8 (labeled "Fused_4," "Fused_6,"',
            'results of updated algorithms and available test images may',
        ]
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                self.assertFalse(looks_like_section_heading(fragment))
                self.assertFalse(looks_like_heading_text(fragment))
                self.assertEqual(classify_heading(fragment), '')

    def test_two_column_paper_extraction_keeps_only_real_headings(self):
        paper = """The Multimodal Brain Tumor Image Segmentation Benchmark

Abstract
This paper reports the set-up and results of the BRATS benchmark organized in conjunction with MICCAI.

I. INTRODUCTION
Gliomas are the most frequent primary brain tumors. Many segmentation
methods, however, were validated on relatively small private
datasets, which makes comparison hard.

II. RELATED WORK
Previous studies proposed generative and discriminative models. Some
methods required manual initialization.

III. METHODS
We collected multi-institutional scans and asked teams to submit
results-on the same test data-to our evaluation platform in
a controlled fashion.

Evaluation Metrics and Ranking
We used Dice, sensitivity and Hausdorff distance for ranking.

IV. RESULTS
Segmentation
results are shown in Fig. 8 (labeled Fused_4, Fused_6).
Fused
results of updated algorithms and available test images may
change over time.

V. DISCUSSION
Inter-rater variability limits the achievable Dice score.

VI. CONCLUSION
Fusion of several algorithms outperforms every individual method.

ACKNOWLEDGEMENTS
We thank the organizers.

REFERENCES
[1] Some citation.
"""
        structure = detect_paper_structure(paper)
        # Only genuine headings must appear; no wrapped-body fragments.
        self.assertNotIn('methods, however, were validated', structure['titles'])
        for title in structure['titles']:
            self.assertTrue(looks_like_heading_text(title), title)

        digest = build_structure_digest(paper)
        # Every digest label must be a real heading.
        for label in [line for line in digest.split('\n') if line.startswith('## ')]:
            self.assertTrue(looks_like_heading_text(label[3:]), label)

        self.assertNotIn('Some citation', digest)
        self.assertNotIn('thank the organizers', digest)
        self.assertEqual(structure['concepts'], {
            'abstract', 'introduction', 'related_work', 'methodology', 'results', 'conclusion',
        })

    def test_lowercase_and_inline_canonical_headings_are_detected(self):
        # A single text blob (no line breaks) where headings appear as
        # title-cased canonical phrases at sentence boundaries.
        blob = (
            'The abstract describes the benchmark. The introduction frames the problem. '
            'Related work surveys prior methods. The proposed method trains a segmentation network. '
            'Results report the dice score. The conclusion summarizes the findings. References list prior work.'
        )
        # Add the missing sentence boundaries so the inline fallback can see each
        # canonical heading at a sentence boundary.
        blob = (
            'The abstract describes the benchmark. The introduction frames the problem. '
            'Related work surveys prior methods. The proposed method trains a segmentation network. '
            'Results report the dice score. The conclusion summarizes the findings. References list prior work.'
        )
        blocks = split_paper_blocks(blob)
        titles = [block['title'] for block in blocks]
        self.assertIn('Abstract', titles)
        self.assertIn('Introduction', titles)
        self.assertIn('Related work', titles)
        self.assertIn('Proposed Method', titles)
        self.assertIn('Results', titles)
        self.assertIn('Conclusion', titles)
        self.assertTrue(all(looks_like_heading_text(title) for title in titles))

    def test_unusual_but_legitimate_heading_is_accepted(self):
        # These are structurally valid headings (not a known canonical phrase), so
        # they must pass the structural gate used for AI-returned titles.
        for heading in ['System Overview and Contributions', 'Contributions and Roadmap', 'Threats to Validity']:
            with self.subTest(heading=heading):
                self.assertTrue(looks_like_heading_text(heading))


class SectionLearningPromptTests(TestCase):
    def test_prompt_requires_full_major_section_coverage(self):
        prompt = build_section_learning_prompt(STANDARD_PAPER_TEXT)

        self.assertIn('Do NOT stop after three sections', prompt)
        self.assertIn('Related Work / Literature Review', prompt)
        self.assertIn('Methodology / Proposed Method', prompt)
        self.assertIn('Results / Evaluation / Discussion', prompt)
        self.assertIn('Conclusion', prompt)
        self.assertIn('Never invent a section that is not supported by the text', prompt)

    def test_prompt_no_longer_allows_stopping_at_three_sections(self):
        prompt = build_section_learning_prompt(STANDARD_PAPER_TEXT)

        self.assertNotIn('Return between 3 and 8 sections', prompt)
        self.assertNotIn('between 3 and 8', prompt)

    def test_prompt_instructs_ai_to_identify_major_sections_itself(self):
        prompt = build_section_learning_prompt(VARIANT_PAPER_TEXT)

        self.assertIn('Read the FULL research paper text below and decide the paper', prompt)
        self.assertIn('do not rely on any pre-listed headings', prompt)
        self.assertIn('IGNORE fine-grained SUBSECTIONS', prompt)
        self.assertIn('Dataset Modality', prompt)
        self.assertIn('Implementation Details', prompt)
        self.assertNotIn('HEADINGS DETECTED IN THIS PAPER', prompt)

    def test_prompt_explains_heading_variations(self):
        prompt = build_section_learning_prompt(STANDARD_PAPER_TEXT)

        self.assertIn('Literature Review, Background or Previous Work count as Related Work', prompt)
        self.assertIn('Materials and Methods, Proposed Method', prompt)
        self.assertIn('Experimental Results, Evaluation', prompt)

    def test_prompt_includes_late_sections_of_a_long_paper(self):
        filler = 'This paragraph adds body text to the section so the paper is long. ' * 120
        long_paper = (
            'Abstract\nThe abstract of a long paper.\n\n'
            f'1. Introduction\n{filler}\n\n'
            f'2. Related Work\n{filler}\n\n'
            f'3. Methodology\n{filler}\n\n'
            '4. Results\nThe system reached 91.7 percent accuracy on the benchmark.\n\n'
            '5. Conclusion\nUNIQUECONCLUSIONMARKER shows the approach generalizes.\n'
        )

        prompt = build_section_learning_prompt(long_paper)

        self.assertGreater(len(long_paper), 24000)
        self.assertIn('## Results', prompt)
        self.assertIn('91.7 percent', prompt)
        self.assertIn('## Conclusion', prompt)
        self.assertIn('UNIQUECONCLUSIONMARKER', prompt)

    def test_prompt_stays_within_size_budget(self):
        prompt = build_section_learning_prompt(' '.join(['token'] * 6000))

        self.assertLess(len(prompt), 12000)
        self.assertIn('[truncated]', prompt)

    def test_prompt_keeps_existing_json_contract(self):
        prompt = build_section_learning_prompt(STANDARD_PAPER_TEXT)

        self.assertIn('"sections"', prompt)
        self.assertIn('"title"', prompt)
        self.assertIn('"explanation"', prompt)
        self.assertIn('100-150 word', prompt)
        self.assertIn('expert academic reading tutor', prompt)
        self.assertNotIn('"summary"', prompt)

    def test_empty_text_returns_empty_prompt(self):
        self.assertEqual(build_section_learning_prompt(''), '')


@override_settings(AI_PROVIDER='mock')
class SectionLearningGenerationTests(TestCase):
    def test_all_six_major_sections_are_generated(self):
        _, paper = create_paper('slfullcoverage', STANDARD_PAPER_TEXT)
        response = section_response('Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        self.assertEqual(
            [section.title for section in sections],
            ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion'],
        )
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 6)
        self.assertGreater(len(sections), 3)

    def test_generation_does_not_stop_after_three_sections(self):
        _, paper = create_paper('slmorethanthree', STANDARD_PAPER_TEXT)
        response = section_response(
            'Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion', 'Limitations',
            'Dataset', 'Implementation', 'Future Work',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 8)
        self.assertEqual([section.section_order for section in sections], list(range(1, 9)))

    def test_heading_variations_are_generated_with_original_titles(self):
        _, paper = create_paper('slvariants', VARIANT_PAPER_TEXT)
        response = section_response(
            'Abstract', 'Introduction', 'Background', 'Proposed Approach', 'Experimental Results',
            'Conclusions and Future Work',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertEqual(len(titles), 6)
        self.assertEqual(titles, [
            'Abstract', 'Introduction', 'Background', 'Proposed Approach', 'Experimental Results',
            'Conclusions and Future Work',
        ])

    def test_missing_related_work_is_not_fabricated(self):
        _, paper = create_paper('slnorelatedwork', NO_RELATED_WORK_PAPER_TEXT)
        response = section_response(
            'Abstract', 'Introduction', 'Related Work', 'Materials and Methods', 'Results and Discussion', 'Conclusion',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertNotIn('Related Work', titles)
        self.assertEqual(titles, ['Abstract', 'Introduction', 'Materials and Methods', 'Results and Discussion', 'Conclusion'])

    def test_fabrication_guard_keeps_sections_present_in_the_paper(self):
        _, paper = create_paper('slrelatedworkpresent', STANDARD_PAPER_TEXT)
        response = section_response('Introduction', 'Literature Review', 'Methodology', 'Results')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        self.assertIn('Literature Review', [section.title for section in sections])

    def test_fabrication_guard_is_skipped_without_detectable_headings(self):
        _, paper = create_paper(
            'slnoheadingstructure',
            'This report walks through an on device runtime study without using any section headings at all.',
        )
        response = section_response('Main Content')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        self.assertEqual([section.title for section in sections], ['Main Content'])

    def test_back_matter_sections_are_skipped(self):
        _, paper = create_paper('slbackmatter', STANDARD_PAPER_TEXT)
        response = section_response('Introduction', 'Methodology', 'Results', 'Conclusion', 'References', 'Acknowledgements')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertEqual(titles, ['Introduction', 'Methodology', 'Results', 'Conclusion'])

    def test_wrapped_body_fragments_returned_by_ai_are_dropped(self):
        _, paper = create_paper('slgarbage', STANDARD_PAPER_TEXT)
        garbage_response = (
            '{"sections": ['
            '{"title": "Introduction", "explanation": "The problem is introduced here."},'
            '{"title": "methods, however, were validated on relatively small private", "explanation": "Irrelevant fragment."},'
            '{"title": "results are shown in Fig. 8 (labeled Fused_4, Fused_6,", "explanation": "Another fragment."},'
            '{"title": "Methodology", "explanation": "The approach is explained."},'
            '{"title": "Results", "explanation": "The findings are summarized."},'
            '{"title": "Conclusion", "explanation": "The study is wrapped up."}'
            ']}'
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=garbage_response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertEqual(
            titles,
            ['Introduction', 'Methodology', 'Results', 'Conclusion'],
        )
        self.assertNotIn('methods, however', titles)
        self.assertNotIn('results are shown', titles)

    def test_non_heading_title_that_lacks_explanation_is_not_generated(self):
        _, paper = create_paper('slnonheading2', STANDARD_PAPER_TEXT)
        # Only valid sections plus one caption-like title, some with empty text.
        response = section_response('Abstract', 'Introduction', 'Methodology', 'Results', 'Conclusion')
        extra = ', {"title": "Fig. 7. Sample segmentation outputs.", "explanation": "This should be dropped too."}'
        response = response[:-2] + extra + ']}'

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertNotIn('Fig. 7. Sample segmentation outputs.', titles)
        self.assertEqual(
            titles,
            ['Abstract', 'Introduction', 'Methodology', 'Results', 'Conclusion'],
        )

    def test_subsections_are_not_created_as_separate_sections(self):
        # A paper whose detected headings include fine-grained subsections.
        paper_text = """Abstract
This study evaluates segmentation models on a public benchmark dataset.

1. Introduction
The problem is introduced.

2. Datasets
We describe the collections used. Dataset Modality Distribution is summarized here.
The modality covers CT and MRI scans.

3. Methodology
We train an encoder-decoder network. Implementation Details are provided in this section.

4. Results and Discussion
The model reaches strong Dice scores across all modalities.

5. Conclusion
We summarize the findings.
"""
        _, paper = create_paper('slsubsections', paper_text)
        response = section_response(
            'Abstract', 'Introduction', 'Datasets', 'Dataset Modality', 'Dataset Modality Distribution',
            'Methodology', 'Implementation Details', 'Results and Discussion', 'Conclusion',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertNotIn('Dataset Modality', titles)
        self.assertNotIn('Dataset Modality Distribution', titles)
        self.assertNotIn('Implementation Details', titles)
        for major in ['Abstract', 'Introduction', 'Methodology', 'Results and Discussion', 'Conclusion']:
            self.assertIn(major, titles)


class SectionLearningPromptTests(TestCase):
    def test_prompt_forbids_sentence_like_titles(self):
        prompt = build_section_learning_prompt(STANDARD_PAPER_TEXT)

        self.assertIn('Never use a sentence, a sentence fragment', prompt)
        self.assertIn('subsection heading', prompt)
        self.assertIn('line of body text as a title', prompt)

    def test_duplicate_heading_variants_are_deduplicated(self):
        _, paper = create_paper('sldupvariants', STANDARD_PAPER_TEXT)
        response = section_response('Introduction', '4 Results', 'RESULTS', 'Results:', 'Conclusion')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        self.assertEqual([section.title for section in sections], ['Introduction', 'Results', 'Conclusion'])

    def test_section_cap_protects_major_sections(self):
        _, paper = create_paper('slcap', STANDARD_PAPER_TEXT)
        extras = [f'Dataset {index}' for index in range(1, 11)]
        response = section_response(
            'Introduction', *extras[:5], 'Related Work', 'Methodology', *extras[5:], 'Results', 'Conclusion', 'Abstract',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response):
            sections = generate_section_learning(paper)

        titles = [section.title for section in sections]
        self.assertEqual(len(titles), SECTION_LEARNING_MAX_SECTIONS)
        for major in ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion']:
            self.assertIn(major, titles)
        self.assertEqual([section.section_order for section in sections], list(range(1, SECTION_LEARNING_MAX_SECTIONS + 1)))

    def test_service_requests_a_section_learning_specific_token_budget(self):
        _, paper = create_paper('sltokenbudget', STANDARD_PAPER_TEXT)
        response = section_response('Introduction', 'Methodology', 'Results', 'Conclusion')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response) as mock_generate:
            generate_section_learning(paper)

        self.assertEqual(mock_generate.call_args.kwargs['max_completion_tokens'], SECTION_LEARNING_COMPLETION_TOKENS)
        self.assertEqual(mock_generate.call_args.kwargs['prompt_type'], 'section_detection')
        self.assertEqual(mock_generate.call_args.args[0], 'section_learning')
        self.assertIn('0.71 nDCG@10', mock_generate.call_args.args[1])

    def test_regeneration_replaces_incomplete_sections_without_duplicates(self):
        _, paper = create_paper('slregenerate', STANDARD_PAPER_TEXT)
        for order, title in enumerate(['Abstract', 'Introduction', 'Methodology'], start=1):
            PaperSection.objects.create(paper=paper, title=title, section_order=order, summary='Old summary.', is_generated=True)

        response = section_response('Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion')

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response) as mock_generate:
            sections = generate_section_learning(paper, force_refresh=True)

        self.assertEqual(len(sections), 6)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 6)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertFalse(PaperSection.objects.filter(paper=paper, summary='Old summary.').exists())
        titles = [section.title for section in sections]
        self.assertEqual(len(titles), len(set(titles)))

    def test_existing_sections_are_reused_without_calling_the_provider(self):
        _, paper = create_paper('slreuse', STANDARD_PAPER_TEXT)
        PaperSection.objects.create(paper=paper, title='Abstract', section_order=1, summary='Kept summary.', is_generated=True)

        with patch('papers.section_learning_service.AIService.generate_feature') as mock_generate:
            sections = generate_section_learning(paper)

        mock_generate.assert_not_called()
        self.assertEqual([section.summary for section in sections], ['Kept summary.'])

    def test_response_without_usable_sections_raises_section_learning_error(self):
        _, paper = create_paper('slnosections', STANDARD_PAPER_TEXT)

        with patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections": []}'):
            with self.assertRaises(SectionLearningError):
                generate_section_learning(paper)

        self.assertFalse(PaperSection.objects.filter(paper=paper).exists())


@override_settings(AI_PROVIDER='mock')
class SectionLearningViewTests(TestCase):
    def test_page_renders_more_than_three_generated_sections(self):
        user, paper = create_paper('slviewuser', STANDARD_PAPER_TEXT)
        create_premium_subscription(user)
        self.client.force_login(user)
        response_payload = section_response(
            'Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion',
        )

        with patch('papers.section_learning_service.AIService.generate_feature', return_value=response_payload):
            response = self.client.post(reverse('paper_sections', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Section Learning generated successfully.')
        for title in ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results', 'Conclusion']:
            self.assertContains(response, title)
        self.assertEqual(len(response.context['section_learning_sections']), 6)


class SectionLearningIsolationTests(TestCase):
    def test_other_feature_prompts_and_services_do_not_use_the_section_normalizer(self):
        import inspect

        from . import (
            flashcard_service,
            glossary_service,
            quiz_service,
            revision_notes_service,
            technical_service,
            viva_service,
        )
        from .prompts import base as base_prompt
        from .prompts import flashcards as flashcards_prompt
        from .prompts import quiz as quiz_prompt
        from .prompts import viva as viva_prompt

        modules = (
            flashcard_service, glossary_service, quiz_service, revision_notes_service,
            technical_service, viva_service, base_prompt, flashcards_prompt, quiz_prompt, viva_prompt,
        )
        for module in modules:
            with self.subTest(module=module.__name__):
                self.assertNotIn('section_normalizer', inspect.getsource(module))

    def test_shared_feature_prompt_and_validator_are_unchanged(self):
        from .prompts.base import build_feature_prompt
        from .response_validator import validate_json_response

        prompt = build_feature_prompt('Paper text', 'glossary', 'Do glossary things.')
        self.assertIn('Return ONLY valid JSON', prompt)
        self.assertIn('"viva_questions"', prompt)

        valid, payload, error = validate_json_response('{"glossary": []}')
        self.assertTrue(valid)
        self.assertEqual(payload, {'glossary': []})
        self.assertEqual(error, '')
