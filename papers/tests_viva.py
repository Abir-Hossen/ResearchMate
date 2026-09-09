"""Focused tests for the isolated Viva Preparation generation pipeline.

Scope is limited to Viva Preparation: prompt shape, viva-specific parsing and
validation, persistence safety, and user-facing error messages.
"""

from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import LearningProgress, Paper, PaperContent, VivaQuestion
from .prompts.viva import VIVA_MAX_CONTEXT_CHARS, build_viva_prompt
from .viva_parser import (
    VIVA_MAXIMUM_QUESTIONS,
    VIVA_MINIMUM_QUESTIONS,
    parse_viva_response,
)
from .viva_service import (
    VIVA_INSUFFICIENT_RESPONSE_MESSAGE,
    VivaGenerationError,
    generate_viva_questions,
)


def build_structured_response(count=5, start=1):
    blocks = []
    for index in range(start, start + count):
        blocks.append(
            f'QUESTION: What does contribution {index} of the paper demonstrate?\n'
            f'ANSWER: Contribution {index} demonstrates that the proposed approach improves the reported metric.\n'
            'CATEGORY: Technical Understanding\n'
            'DIFFICULTY: Medium\n'
            f'TIP: Mention the evidence for contribution {index}.'
        )
    return '\n\n'.join(blocks)


def build_legacy_json_response(count=5):
    items = []
    for index in range(1, count + 1):
        items.append(
            '{"question": "Legacy question %d?", "suggested_answer": "Legacy answer %d explains the result.", '
            '"difficulty": "Hard", "category": "Critical Thinking", "examiner_tip": "Legacy tip %d."}'
            % (index, index, index)
        )
    return '{"viva_questions": [' + ', '.join(items) + ']}'


def build_truncated_json_response(complete_items=6):
    """Mimic the real failure: a valid JSON prefix cut off at the token limit."""
    items = []
    for index in range(1, complete_items + 1):
        items.append(
            '{"question": "Truncated set question %d?", "suggested_answer": "%s", '
            '"difficulty": "Medium", "category": "Basic Understanding", "examiner_tip": "Be specific."}'
            % (index, 'This answer is intentionally long to consume output tokens. ' * 4)
        )
    body = ', '.join(items)
    return (
        '{"viva_questions": [' + body
        + ', {"question": "This final question was cut off mid-string?", "suggested_answer": "The provider stopped'
    )


def create_paper_with_content(username, extracted_text='Extracted paper text for viva generation.'):
    user = User.objects.create_user(username=username, password='Secret123')
    paper = Paper.objects.create(owner=user, title=f'{username} Paper', pdf_file='papers/example.pdf')
    PaperContent.objects.create(paper=paper, extracted_text=extracted_text, extraction_status='Ready')
    return user, paper


def provider_returning(response):
    provider = Mock()
    provider.generate.return_value = response
    provider.model_name = 'test-model'
    return provider


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


class VivaPromptTests(TestCase):
    def test_viva_prompt_requests_structured_question_answer_text(self):
        prompt = build_viva_prompt('Paper body about graph neural networks.')

        self.assertIn('QUESTION: <one clear viva question>', prompt)
        self.assertIn('ANSWER: <a self-contained answer of 60 to 110 words>', prompt)
        self.assertIn('Paper body about graph neural networks.', prompt)

    def test_viva_prompt_does_not_request_json_or_code_fences(self):
        prompt = build_viva_prompt('Paper body.')

        self.assertNotIn('"viva_questions"', prompt)
        self.assertNotIn('Return ONLY valid JSON', prompt)
        self.assertIn('Do NOT return JSON', prompt)
        self.assertIn('markdown code fences', prompt)

    def test_viva_prompt_limits_paper_context_to_reduce_truncation(self):
        prompt = build_viva_prompt('x' * (VIVA_MAX_CONTEXT_CHARS + 5000))

        self.assertIn('x' * VIVA_MAX_CONTEXT_CHARS, prompt)
        self.assertNotIn('x' * (VIVA_MAX_CONTEXT_CHARS + 1), prompt)


class VivaParserTests(TestCase):
    def test_valid_json_payload_is_parsed(self):
        entries = parse_viva_response(build_legacy_json_response(count=4))

        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0]['question'], 'Legacy question 1?')
        self.assertEqual(entries[0]['suggested_answer'], 'Legacy answer 1 explains the result.')
        self.assertEqual(entries[0]['difficulty'], 'Hard')
        self.assertEqual(entries[0]['category'], 'Critical Thinking')
        self.assertEqual(entries[0]['examiner_tip'], 'Legacy tip 1.')
        self.assertEqual(entries[0]['follow_up_question'], '')

    def test_valid_json_with_answer_key_and_follow_up_is_parsed(self):
        raw = (
            '{"viva_questions": [{"question": "What is the aim?", "answer": "The aim is to improve accuracy.", '
            '"follow_up_question": "Why does accuracy matter?"}]}'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['suggested_answer'], 'The aim is to improve accuracy.')
        self.assertEqual(entries[0]['examiner_tip'], 'Why does accuracy matter?')
        self.assertEqual(entries[0]['difficulty'], 'Medium')
        self.assertEqual(entries[0]['category'], 'Basic Understanding')

    def test_bare_json_list_is_parsed(self):
        raw = '[{"question": "What problem is solved?", "answer": "It solves data sparsity."}]'
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['question'], 'What problem is solved?')

    def test_structured_text_pairs_are_parsed(self):
        entries = parse_viva_response(build_structured_response(count=6))

        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0]['question'], 'What does contribution 1 of the paper demonstrate?')
        self.assertEqual(entries[0]['category'], 'Technical Understanding')
        self.assertEqual(entries[0]['difficulty'], 'Medium')
        self.assertEqual(entries[5]['display_order'], 6)

    def test_structured_text_with_labels_on_their_own_lines_is_parsed(self):
        raw = (
            'QUESTION:\n'
            'What is the primary objective of the research?\n'
            'ANSWER:\n'
            'The primary objective is to reduce inference latency.\n'
            '\n'
            'QUESTION:\n'
            'Why was this methodology selected?\n'
            'ANSWER:\n'
            'The methodology was selected because it matches the dataset size.\n'
            '\n'
            'QUESTION: How were the results validated?\n'
            'ANSWER: The results were validated with a held-out test split.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['question'], 'What is the primary objective of the research?')
        self.assertEqual(entries[1]['suggested_answer'], 'The methodology was selected because it matches the dataset size.')
        self.assertEqual(entries[2]['question'], 'How were the results validated?')

    def test_multiline_question_is_parsed(self):
        raw = (
            'QUESTION: Considering the evaluation protocol described in section four,\n'
            'why did the authors report macro averaged scores?\n'
            'ANSWER: Because the classes are imbalanced.\n'
            '\n'
            'QUESTION: What dataset was used?\n'
            'ANSWER: A public benchmark dataset.\n'
            '\n'
            'QUESTION: What is the stated limitation?\n'
            'ANSWER: The study covers a single domain.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(
            entries[0]['question'],
            'Considering the evaluation protocol described in section four, why did the authors report macro averaged scores?',
        )

    def test_multiline_answer_is_parsed(self):
        raw = (
            'QUESTION: What is the contribution?\n'
            'ANSWER: The paper introduces a lightweight architecture.\n'
            'It also releases an annotated dataset.\n'
            'Finally it reports an ablation study.\n'
            '\n'
            'QUESTION: What is the baseline?\n'
            'ANSWER: A standard convolutional model.\n'
            '\n'
            'QUESTION: What metric is reported?\n'
            'ANSWER: F1 score on the test split.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(
            entries[0]['suggested_answer'],
            'The paper introduces a lightweight architecture. It also releases an annotated dataset. '
            'Finally it reports an ablation study.',
        )

    def test_malformed_item_is_skipped_and_valid_items_are_kept(self):
        raw = (
            'QUESTION: What is the research gap?\n'
            'ANSWER: Existing work ignores noisy labels.\n'
            '\n'
            'QUESTION: This question has no answer at all\n'
            '\n'
            'QUESTION: What is the proposed fix?\n'
            'ANSWER: A robust loss function.\n'
            '\n'
            'QUESTION: How is it evaluated?\n'
            'ANSWER: With five fold cross validation.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        questions = [entry['question'] for entry in entries]
        self.assertNotIn('This question has no answer at all', questions)
        self.assertEqual([entry['display_order'] for entry in entries], [1, 2, 3])

    def test_empty_question_is_rejected(self):
        raw = (
            'QUESTION:\n'
            'ANSWER: An answer without a question must be discarded.\n'
            '\n'
            'QUESTION: What is the dataset?\n'
            'ANSWER: A curated corpus of abstracts.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['question'], 'What is the dataset?')

    def test_empty_answer_is_rejected(self):
        raw = (
            'QUESTION: What is the dataset?\n'
            'ANSWER:\n'
            '\n'
            'QUESTION: What is the metric?\n'
            'ANSWER: Accuracy on the held out split.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['question'], 'What is the metric?')

    def test_empty_json_question_or_answer_is_rejected(self):
        raw = (
            '{"viva_questions": ['
            '{"question": "", "suggested_answer": "Answer without a question."},'
            '{"question": "Question without an answer?", "suggested_answer": "   "},'
            '{"question": "Valid question?", "suggested_answer": "Valid answer."}'
            ']}'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['question'], 'Valid question?')

    def test_duplicate_questions_are_deduplicated(self):
        raw = (
            'QUESTION: What is the objective?\n'
            'ANSWER: To improve retrieval quality.\n'
            '\n'
            'QUESTION: what is the objective?\n'
            'ANSWER: A duplicate answer that must be dropped.\n'
            '\n'
            'QUESTION: What is the limitation?\n'
            'ANSWER: Only English data was used.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['suggested_answer'], 'To improve retrieval quality.')
        self.assertEqual([entry['display_order'] for entry in entries], [1, 2])

    def test_markdown_code_fences_do_not_break_parsing(self):
        raw = '```text\n' + build_structured_response(count=4) + '\n```'
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 4)

    def test_markdown_code_fences_around_json_do_not_break_parsing(self):
        raw = '```json\n' + build_legacy_json_response(count=3) + '\n```'
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)

    def test_extra_blank_lines_and_windows_line_endings_do_not_break_parsing(self):
        raw = build_structured_response(count=4).replace('\n\n', '\r\n\r\n\r\n\r\n').replace('\n', '\r\n')
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 4)

    def test_decorative_separator_lines_are_ignored(self):
        raw = (
            'QUESTION: What is the objective?\n'
            'ANSWER: To improve ranking quality.\n'
            'TIP: Frame the objective first.\n'
            '\n---\n\n'
            'QUESTION: What is the dataset?\n'
            'ANSWER: A scholarly citation corpus.\n'
            '\n***\n\n'
            'QUESTION: What is the limitation?\n'
            'ANSWER: English only evaluation.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['examiner_tip'], 'Frame the objective first.')
        self.assertEqual(entries[1]['question'], 'What is the dataset?')

    def test_commentary_before_and_after_items_is_ignored(self):
        raw = (
            'Sure! Here are the viva questions you asked for:\n\n'
            'QUESTION: What is the core idea?\n'
            'ANSWER: A two stage retrieval pipeline.\n'
            '\n'
            'QUESTION: What is the dataset?\n'
            'ANSWER: An open access citation graph.\n'
            '\n'
            'QUESTION: What is future work?\n'
            'ANSWER: Extending to multilingual data.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['question'], 'What is the core idea?')

    def test_bold_and_numbered_labels_are_tolerated(self):
        raw = (
            '**QUESTION 1:** What is the aim of the study?\n'
            '**ANSWER:** To benchmark three optimizers.\n'
            '\n'
            '2. QUESTION: Which optimizer performed best?\n'
            '- ANSWER: The adaptive optimizer performed best.\n'
            '\n'
            'Q: What was measured?\n'
            'A: Convergence speed and final accuracy.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]['question'], 'What is the aim of the study?')
        self.assertEqual(entries[0]['suggested_answer'], 'To benchmark three optimizers.')
        self.assertEqual(entries[2]['question'], 'What was measured?')

    def test_missing_metadata_falls_back_to_defaults(self):
        raw = (
            'QUESTION: What is measured?\n'
            'ANSWER: Precision and recall.\n'
            '\n'
            'QUESTION: What is the baseline?\n'
            'ANSWER: A rule based system.\n'
            '\n'
            'QUESTION: What is the conclusion?\n'
            'ANSWER: The learned model wins.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 3)
        for entry in entries:
            self.assertEqual(entry['difficulty'], 'Medium')
            self.assertEqual(entry['category'], 'Basic Understanding')
            self.assertEqual(entry['examiner_tip'], '')

    def test_category_and_difficulty_values_are_normalized(self):
        raw = (
            'QUESTION: What is the aim?\n'
            'ANSWER: To reduce error rates.\n'
            'CATEGORY: critical thinking\n'
            'DIFFICULTY: moderate\n'
            '\n'
            'QUESTION: What is the method?\n'
            'ANSWER: A transformer encoder.\n'
            'CATEGORY: Technical understanding of the model\n'
            'DIFFICULTY: DIFFICULT\n'
            '\n'
            'QUESTION: What is the dataset?\n'
            'ANSWER: A public corpus.\n'
            'CATEGORY: Basic\n'
            'DIFFICULTY: easy'
        )
        entries = parse_viva_response(raw)

        self.assertEqual([entry['category'] for entry in entries], [
            'Critical Thinking',
            'Technical Understanding',
            'Basic Understanding',
        ])
        self.assertEqual([entry['difficulty'] for entry in entries], ['Medium', 'Hard', 'Easy'])

    def test_truncated_json_response_recovers_complete_items(self):
        raw = build_truncated_json_response(complete_items=6)
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0]['question'], 'Truncated set question 1?')
        questions = [entry['question'] for entry in entries]
        self.assertNotIn('This final question was cut off mid-string?', questions)

    def test_truncated_structured_text_keeps_complete_items(self):
        raw = build_structured_response(count=4) + '\n\nQUESTION: This trailing question was cut off'
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 4)

    def test_placeholder_template_values_are_rejected(self):
        raw = (
            'QUESTION: <question text>\n'
            'ANSWER: <answer text>\n'
            '\n'
            'QUESTION: What is the real question?\n'
            'ANSWER: The real answer.'
        )
        entries = parse_viva_response(raw)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['question'], 'What is the real question?')

    def test_unusable_response_returns_empty_list_without_raising(self):
        for raw in ['', '   ', None, 'Sorry, I cannot help with that request.', '{"viva_questions": []}']:
            with self.subTest(raw=raw):
                self.assertEqual(parse_viva_response(raw), [])

    def test_parser_never_raises_on_broken_json_fragment(self):
        raw = '{"viva_questions": [{"question": "Broken?", "suggested_answer": "Missing closing'
        self.assertEqual(parse_viva_response(raw), [])


class VivaGenerationServiceTests(TestCase):
    def test_structured_text_response_is_persisted(self):
        _, paper = create_paper_with_content('vivastructured')
        provider = provider_returning(build_structured_response(count=6))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            created = generate_viva_questions(paper)

        self.assertEqual(len(created), 6)
        self.assertEqual(VivaQuestion.objects.filter(paper=paper).count(), 6)
        first = VivaQuestion.objects.filter(paper=paper).order_by('display_order').first()
        self.assertEqual(first.question, 'What does contribution 1 of the paper demonstrate?')
        self.assertEqual(first.category, 'Technical Understanding')
        self.assertEqual(first.difficulty, 'Medium')
        self.assertEqual(first.examiner_tip, 'Mention the evidence for contribution 1.')
        self.assertEqual(first.display_order, 1)

        progress = LearningProgress.objects.get(paper=paper)
        self.assertTrue(progress.viva_completed)
        self.assertIsNotNone(progress.last_accessed)

    def test_legacy_valid_json_response_is_still_supported(self):
        _, paper = create_paper_with_content('vivalegacyjson')
        provider = provider_returning(build_legacy_json_response(count=5))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            created = generate_viva_questions(paper)

        self.assertEqual(len(created), 5)
        self.assertEqual(created[0].question, 'Legacy question 1?')
        self.assertEqual(created[0].suggested_answer, 'Legacy answer 1 explains the result.')
        self.assertTrue(LearningProgress.objects.get(paper=paper).viva_completed)

    def test_truncated_json_response_no_longer_fails_generation(self):
        _, paper = create_paper_with_content('vivatruncated')
        provider = provider_returning(build_truncated_json_response(complete_items=8))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            created = generate_viva_questions(paper)

        self.assertEqual(len(created), 8)
        self.assertEqual(VivaQuestion.objects.filter(paper=paper).count(), 8)

    def test_response_below_minimum_fails_gracefully_without_saving(self):
        _, paper = create_paper_with_content('vivaminimum')
        provider = provider_returning(build_structured_response(count=VIVA_MINIMUM_QUESTIONS - 1))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            with self.assertRaises(VivaGenerationError) as error:
                generate_viva_questions(paper)

        self.assertEqual(str(error.exception), VIVA_INSUFFICIENT_RESPONSE_MESSAGE)
        self.assertFalse(VivaQuestion.objects.filter(paper=paper).exists())
        self.assertFalse(LearningProgress.objects.filter(paper=paper, viva_completed=True).exists())

    def test_minimum_valid_items_are_accepted(self):
        _, paper = create_paper_with_content('vivaexactminimum')
        provider = provider_returning(build_structured_response(count=VIVA_MINIMUM_QUESTIONS))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            created = generate_viva_questions(paper)

        self.assertEqual(len(created), VIVA_MINIMUM_QUESTIONS)

    def test_error_message_never_exposes_json_parsing_internals(self):
        _, paper = create_paper_with_content('vivajsonleak')
        broken_json = '{"viva_questions": [{"question": "Broken item?", "suggested_answer": "Cut off'
        provider = provider_returning(broken_json)

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            with self.assertRaises(VivaGenerationError) as error:
                generate_viva_questions(paper)

        message = str(error.exception)
        self.assertEqual(message, VIVA_INSUFFICIENT_RESPONSE_MESSAGE)
        for forbidden in ["Expecting ',' delimiter", 'json.loads', 'JSONDecodeError', 'Traceback', 'char 1']:
            self.assertNotIn(forbidden, message)

    def test_failed_generation_keeps_existing_viva_questions(self):
        _, paper = create_paper_with_content('vivakeepexisting')
        VivaQuestion.objects.create(
            paper=paper,
            question='Existing question?',
            suggested_answer='Existing answer.',
            difficulty='Easy',
            category='Basic Understanding',
            display_order=1,
        )
        provider = provider_returning('This response is not usable at all.')

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            questions = generate_viva_questions(paper)

        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0].question, 'Existing question?')
        self.assertEqual(VivaQuestion.objects.filter(paper=paper).count(), 1)
        provider.generate.assert_not_called()

    def test_regeneration_does_not_create_duplicate_records(self):
        _, paper = create_paper_with_content('vivaregenerate')
        provider = provider_returning(build_structured_response(count=5))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            generate_viva_questions(paper)
            generate_viva_questions(paper)

        self.assertEqual(VivaQuestion.objects.filter(paper=paper).count(), 5)
        self.assertEqual(provider.generate.call_count, 1)

    def test_saved_questions_are_capped_at_maximum(self):
        _, paper = create_paper_with_content('vivacap')
        provider = provider_returning(build_structured_response(count=VIVA_MAXIMUM_QUESTIONS + 4))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            created = generate_viva_questions(paper)

        self.assertEqual(len(created), VIVA_MAXIMUM_QUESTIONS)
        self.assertEqual(VivaQuestion.objects.filter(paper=paper).count(), VIVA_MAXIMUM_QUESTIONS)

    def test_empty_provider_response_returns_viva_specific_message(self):
        _, paper = create_paper_with_content('vivaempty')
        provider = provider_returning('   ')

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            with self.assertRaises(VivaGenerationError) as error:
                generate_viva_questions(paper)

        self.assertEqual(str(error.exception), 'The AI provider returned an empty viva response.')
        self.assertFalse(VivaQuestion.objects.filter(paper=paper).exists())

    def test_provider_exception_returns_friendly_message(self):
        _, paper = create_paper_with_content('vivaproviderfail')
        provider = Mock()
        provider.generate.side_effect = RuntimeError('Groq unavailable')

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            with self.assertRaises(VivaGenerationError) as error:
                generate_viva_questions(paper)

        self.assertEqual(str(error.exception), 'Viva question generation failed. Please try again later.')
        self.assertFalse(VivaQuestion.objects.filter(paper=paper).exists())

    def test_generation_requires_paper_content(self):
        user = User.objects.create_user(username='vivanocontent', password='Secret123')
        paper = Paper.objects.create(owner=user, title='No Content Paper', pdf_file='papers/none.pdf')

        with self.assertRaises(VivaGenerationError) as error:
            generate_viva_questions(paper)

        self.assertIn('Paper content must exist', str(error.exception))

    def test_generation_requires_extracted_text(self):
        _, paper = create_paper_with_content('vivablanktext', extracted_text='   ')

        with self.assertRaises(VivaGenerationError) as error:
            generate_viva_questions(paper)

        self.assertIn('must contain extracted text', str(error.exception))

    def test_prompt_sent_to_provider_is_the_viva_structured_prompt(self):
        _, paper = create_paper_with_content('vivapromptused')
        provider = provider_returning(build_structured_response(count=4))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            generate_viva_questions(paper)

        prompt = provider.generate.call_args[0][0]
        self.assertIn('QUESTION: <one clear viva question>', prompt)
        self.assertNotIn('"viva_questions"', prompt)


@override_settings(AI_PROVIDER='mock')
class VivaWorkspaceViewTests(TestCase):
    def setUp(self):
        self.user, self.paper = create_paper_with_content('vivaviewuser')
        create_premium_subscription(self.user)
        self.client.force_login(self.user)

    def test_post_generates_and_renders_questions(self):
        provider = provider_returning(build_structured_response(count=5))

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            response = self.client.post(reverse('paper_viva', args=[self.paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Viva questions generated successfully.')
        self.assertContains(response, 'What does contribution 1 of the paper demonstrate?')
        self.assertContains(response, 'Show answer')
        self.assertContains(response, 'Technical Understanding')
        self.assertEqual(VivaQuestion.objects.filter(paper=self.paper).count(), 5)

    def test_post_failure_shows_viva_specific_message_only(self):
        provider = provider_returning('{"viva_questions": [{"question": "Broken?", "suggested_answer": "Cut off')

        with patch('papers.viva_service.ProviderFactory.create_provider', return_value=provider):
            response = self.client.post(reverse('paper_viva', args=[self.paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, VIVA_INSUFFICIENT_RESPONSE_MESSAGE)
        self.assertNotContains(response, 'delimiter')
        self.assertNotContains(response, 'JSONDecodeError')
        self.assertNotContains(response, 'Traceback')
        self.assertFalse(VivaQuestion.objects.filter(paper=self.paper).exists())

    def test_get_renders_existing_questions_grouped_by_category(self):
        VivaQuestion.objects.create(
            paper=self.paper,
            question='Stored basic question?',
            suggested_answer='Stored basic answer.',
            difficulty='Easy',
            category='Basic Understanding',
            examiner_tip='Stay concise.',
            display_order=1,
        )
        VivaQuestion.objects.create(
            paper=self.paper,
            question='Stored critical question?',
            suggested_answer='Stored critical answer.',
            difficulty='Hard',
            category='Critical Thinking',
            display_order=2,
        )

        response = self.client.get(reverse('paper_viva', args=[self.paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stored basic question?')
        self.assertContains(response, 'Stored critical question?')
        self.assertContains(response, 'Basic Understanding')
        self.assertContains(response, 'Critical Thinking')
        self.assertContains(response, 'Stay concise.')
        self.assertEqual(list(response.context['grouped_viva_questions'].keys()), ['Basic Understanding', 'Critical Thinking'])


class VivaIsolationRegressionTests(TestCase):
    def test_shared_feature_prompt_still_requests_json_for_other_features(self):
        from .prompts.base import build_feature_prompt

        prompt = build_feature_prompt('Paper text', 'glossary', 'Do glossary things.')
        self.assertIn('Return ONLY valid JSON', prompt)
        self.assertIn('"glossary"', prompt)

    def test_shared_response_validator_behaviour_is_unchanged(self):
        from .response_validator import validate_json_response

        valid, payload, error = validate_json_response('{"flashcards": []}')
        self.assertTrue(valid)
        self.assertEqual(payload, {'flashcards': []})
        self.assertEqual(error, '')

        valid, payload, error = validate_json_response('{"flashcards": [')
        self.assertFalse(valid)
        self.assertIsNone(payload)
        self.assertNotEqual(error, '')

    def test_other_feature_services_do_not_import_the_viva_parser(self):
        import inspect

        from . import (
            flashcard_service,
            glossary_service,
            quiz_service,
            revision_notes_service,
            section_learning_service,
            technical_service,
        )

        for module in (
            flashcard_service,
            glossary_service,
            quiz_service,
            revision_notes_service,
            section_learning_service,
            technical_service,
        ):
            with self.subTest(module=module.__name__):
                self.assertNotIn('viva_parser', inspect.getsource(module))
