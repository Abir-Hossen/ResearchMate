import os
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.pdfgen import canvas

from .models import AIAnalysis, Flashcard, Glossary, LearningProgress, Paper, PaperContent, PaperSection, QuizQuestion, VivaQuestion
from .prompts.beginner import build_beginner_prompt
from .prompts.glossary import build_glossary_prompt
from .prompts.revision_notes import build_revision_notes_prompt
from .prompts.section_learning import build_section_learning_prompt
from .prompts.technical import build_technical_prompt
from .response_validator import validate_json_response
from .services import _get_user_facing_error_message
from .flashcard_service import FlashcardGenerationError, generate_flashcards
from .quiz_service import QuizGenerationError, generate_quiz


class GroqConnectivityTests(TestCase):
    @override_settings(DEBUG=True, GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
    @patch('papers.groq_connectivity.GroqLearningService.test_connection', return_value={
        'model': 'llama-3.3-70b-versatile',
        'response': 'Groq connected',
        'elapsed': 0.123,
    })
    def test_groq_debug_view_shows_status_and_response(self, mock_test_connection):
        response = self.client.get(reverse('groq_test'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'API key loaded')
        self.assertContains(response, 'Model name')
        self.assertContains(response, 'Connection successful')
        self.assertContains(response, 'AI response')
        self.assertContains(response, 'Response time')
        self.assertContains(response, 'Groq connected')

    def test_load_env_file_refreshes_groq_settings(self):
        from ResearchMate import settings as project_settings

        with tempfile.NamedTemporaryFile('w', delete=False, dir=str(project_settings.BASE_DIR), encoding='utf-8') as handle:
            handle.write('GROQ_API_KEY=test-from-env\n')
            handle.write('GROQ_MODEL=test-model\n')
            handle.write('AI_PROVIDER=groq\n')
            temp_path = Path(handle.name)

        try:
            project_settings.load_env_file(env_file=temp_path)
            self.assertEqual(os.environ['GROQ_API_KEY'], 'test-from-env')
            self.assertEqual(project_settings.GROQ_API_KEY, 'test-from-env')
            self.assertEqual(project_settings.GROQ_MODEL, 'test-model')
        finally:
            temp_path.unlink(missing_ok=True)


class AdminMonitoringTests(TestCase):
    def test_admin_problem_monitoring_filters_are_configured(self):
        from .admin import AIAnalysisAdmin, LearningProgressAdmin, PaperAdmin

        self.assertIn('processing_status', PaperAdmin.list_filter)
        self.assertIn('ai_analysis__analysis_status', PaperAdmin.list_filter)
        self.assertIn('ai_analysis__ai_model', PaperAdmin.list_filter)
        self.assertIn('title', PaperAdmin.search_fields)
        self.assertIn('owner__username', PaperAdmin.search_fields)

        self.assertIn('analysis_status', AIAnalysisAdmin.list_filter)
        self.assertIn('ai_model', AIAnalysisAdmin.list_filter)
        self.assertIn('paper__processing_status', AIAnalysisAdmin.list_filter)
        self.assertIn('paper__title', AIAnalysisAdmin.search_fields)

        self.assertIn('overall_progress', LearningProgressAdmin.list_filter)
        self.assertIn('paper__title', LearningProgressAdmin.search_fields)


class AdminSecurityTests(TestCase):
    def test_non_staff_user_cannot_access_admin(self):
        user = User.objects.create_user(username='basicuser', password='Secret123')
        self.client.force_login(user)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response.url)

    def test_staff_user_can_access_admin_index(self):
        user = User.objects.create_user(username='adminuser', password='Secret123', is_staff=True, is_superuser=True)
        self.client.force_login(user)

        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, 200)

    def test_ai_generated_content_admin_is_read_only(self):
        request = RequestFactory().get('/admin/')
        request.user = User.objects.create_user(username='securityadmin', password='Secret123', is_staff=True, is_superuser=True)

        from .admin import AIAnalysisAdmin
        from .models import AIAnalysis

        admin_obj = AIAnalysisAdmin(AIAnalysis, admin.site)

        self.assertFalse(admin_obj.has_add_permission(request))
        self.assertFalse(admin_obj.has_change_permission(request))
        self.assertFalse(admin_obj.has_delete_permission(request))


class PaperUploadTests(TestCase):
    @override_settings(AI_PROVIDER='mock')
    def test_upload_page_requires_login(self):
        response = self.client.get(reverse('upload_paper'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_user_can_upload_pdf(self):
        user = User.objects.create_user(username='paperuser', password='Secret123')
        self.client.force_login(user)
        pdf = SimpleUploadedFile('sample.pdf', b'%PDF-1.4\n', content_type='application/pdf')

        response = self.client.post(
            reverse('upload_paper'),
            {'title': 'Sample Paper', 'pdf_file': pdf},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Paper.objects.filter(owner=user, title='Sample Paper').exists())
        self.assertContains(response, 'Paper uploaded successfully')
        self.assertRedirects(response, reverse('dashboard'))

    def test_invalid_file_type_is_rejected(self):
        user = User.objects.create_user(username='paperuser2', password='Secret123')
        self.client.force_login(user)
        txt = SimpleUploadedFile('sample.txt', b'hello', content_type='text/plain')

        response = self.client.post(
            reverse('upload_paper'),
            {'title': 'Bad File', 'pdf_file': txt},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only PDF files are allowed.')

    def test_my_papers_page_only_shows_current_user_papers(self):
        owner = User.objects.create_user(username='owner', password='Secret123')
        other = User.objects.create_user(username='other', password='Secret123')
        Paper.objects.create(owner=owner, title='Owner Paper', pdf_file=SimpleUploadedFile('owner.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        Paper.objects.create(owner=other, title='Other Paper', pdf_file=SimpleUploadedFile('other.pdf', b'%PDF-1.4\n', content_type='application/pdf'))

        self.client.force_login(owner)
        response = self.client.get(reverse('my_papers'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Owner Paper')
        self.assertNotContains(response, 'Other Paper')

    def test_delete_paper_removes_file_and_database_record(self):
        user = User.objects.create_user(username='deleteuser', password='Secret123')
        self.client.force_login(user)
        pdf = SimpleUploadedFile('delete.pdf', b'%PDF-1.4\n', content_type='application/pdf')
        paper = Paper.objects.create(owner=user, title='Delete Me', pdf_file=pdf)

        response = self.client.post(reverse('delete_paper', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Paper.objects.filter(pk=paper.pk).exists())
        self.assertFalse(paper.pdf_file.storage.exists(paper.pdf_file.name))
        self.assertContains(response, 'Paper deleted successfully')

    def test_workspace_overview_requires_owner_access(self):
        owner = User.objects.create_user(username='workspaceowner', password='Secret123')
        other = User.objects.create_user(username='workspaceother', password='Secret123')
        paper = Paper.objects.create(owner=owner, title='Protected Paper', pdf_file=SimpleUploadedFile('protected.pdf', b'%PDF-1.4\n', content_type='application/pdf'))

        self.client.force_login(other)
        response = self.client.get(reverse('paper_overview', args=[paper.pk]))

        self.assertEqual(response.status_code, 404)

    def test_anonymous_user_cannot_access_private_paper_workspace(self):
        owner = User.objects.create_user(username='workspaceowneranon', password='Secret123')
        paper = Paper.objects.create(owner=owner, title='Login Protected Paper', pdf_file=SimpleUploadedFile('protected.pdf', b'%PDF-1.4\n', content_type='application/pdf'))

        response = self.client.get(reverse('paper_sections', args=[paper.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_workspace_beginner_page_renders_paper_context(self):
        user = User.objects.create_user(username='workspacebeginner', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Study Paper', pdf_file=SimpleUploadedFile('study.pdf', b'%PDF-1.4\n', content_type='application/pdf'))

        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Study Paper')

    def test_beginner_page_renders_markdown_sections_for_generated_content(self):
        user = User.objects.create_user(username='beginnerlayout', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Beginner Layout Paper', pdf_file=SimpleUploadedFile('layout.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        AIAnalysis.objects.create(
            paper=paper,
            beginner_explanation='## Paper Overview\n\nThis paper studies a new method.\n\n- It is practical.\n- It is useful.',
            analysis_status='Ready',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h2 class="section-title">Paper Overview</h2>')
        self.assertContains(response, '<li>It is practical.</li>')

    def test_beginner_prompt_requests_json_payload_for_pipeline(self):
        prompt = build_beginner_prompt('A sample paper about neural networks.')

        self.assertIn('Return ONLY valid JSON', prompt)
        self.assertIn('"beginner_explanation"', prompt)
        self.assertIn('"technical_explanation"', prompt)
        self.assertIn('"glossary"', prompt)

    def test_technical_prompt_requests_structured_markdown_sections(self):
        prompt = build_technical_prompt('A sample paper about neural networks.')

        self.assertIn('Overall Technical Architecture', prompt)
        self.assertIn('Model Architecture', prompt)
        self.assertIn('Data Processing Pipeline', prompt)
        self.assertIn('Technical Design Decisions', prompt)
        self.assertIn('Experimental Design', prompt)
        self.assertIn('Technical Strengths', prompt)
        self.assertIn('Technical Limitations', prompt)
        self.assertIn('Engineering Takeaways', prompt)
        self.assertIn('500-700 words', prompt)
        self.assertIn('Treat the paper as reference material only', prompt)
        self.assertIn('Never copy text', prompt)
        self.assertIn('Never repeat the title', prompt)
        self.assertIn('senior AI researcher and university professor', prompt)

    def test_technical_page_renders_markdown_sections_for_generated_content(self):
        user = User.objects.create_user(username='technicallayout', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Technical Layout Paper', pdf_file=SimpleUploadedFile('technical.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        AIAnalysis.objects.create(
            paper=paper,
            technical_explanation='## Research Objective\n\nThis paper studies a new method.\n\n- It is practical.\n- It is useful.',
            analysis_status='Ready',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h2 class="section-title">Research Objective</h2>')
        self.assertContains(response, '<li>It is practical.</li>')

    def test_revision_notes_prompt_requests_markdown_output(self):
        prompt = build_revision_notes_prompt('A sample paper about neural networks.')

        self.assertIn('Markdown', prompt)
        self.assertIn('revision notes', prompt)
        self.assertIn('Paper text:', prompt)

    @override_settings(AI_PROVIDER='mock')
    def test_revision_notes_page_generates_and_persists_notes(self):
        user = User.objects.create_user(username='revisionnotesuser', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Revision Notes Paper', pdf_file=SimpleUploadedFile('revision-notes.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper introduces a useful evaluation method.', extraction_status='Ready')

        class StubProvider:
            model_name = 'mock-model'

            def generate(self, prompt):
                return '## Main Takeaway\n\n- Review the evaluation method.'

        self.client.force_login(user)
        with patch('papers.revision_notes_service.ProviderFactory.create_provider', return_value=StubProvider()):
            response = self.client.post(reverse('paper_notes', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.revision_notes, '## Main Takeaway\n\n- Review the evaluation method.')
        self.assertContains(response, '<h2 class="section-title">Main Takeaway</h2>')

    @override_settings(AI_PROVIDER='mock')
    def test_technical_page_shows_generate_button_when_content_is_missing(self):
        user = User.objects.create_user(username='technicalbutton', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Technical Button Paper', pdf_file=SimpleUploadedFile('technical-button.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='Technical button extraction content', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate Technical Explanation')
        self.assertNotContains(response, 'Run Start Learning to generate a technical explanation.')

    def test_section_learning_prompt_requests_section_json_schema(self):
        prompt = build_section_learning_prompt('A sample paper about neural networks.')

        self.assertIn('"sections"', prompt)
        self.assertIn('"title"', prompt)
        self.assertIn('"summary"', prompt)
        self.assertIn('"purpose"', prompt)
        self.assertIn('"key_points"', prompt)
        self.assertIn('"important_terms"', prompt)
        self.assertIn('"student_note"', prompt)
        self.assertIn('Return ONLY valid JSON', prompt)
        self.assertIn('every major section', prompt)
        self.assertIn('Do not stop after Introduction or Related Work', prompt)
        self.assertIn('cover the full paper', prompt)

    def test_section_learning_prompt_compacts_large_section_text(self):
        long_text = ' '.join(['token'] * 4000)

        prompt = build_section_learning_prompt('Methods', long_text)

        self.assertIn('Section text:', prompt)
        self.assertIn('[truncated]', prompt)
        self.assertLess(len(prompt), 12000)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', side_effect=[
        '{"sections":[{"title":"Conclusion","order":1}]}',
        '{"summary":"A concise explanation","purpose":"It wraps up the main point","key_points":["The takeaway is clear"],"important_terms":["takeaway"],"student_note":"Remember the main message","conclusion":"This section closes the learning loop by reinforcing the core takeaway."}',
    ])
    def test_generate_section_learning_persists_conclusion(self, mock_generate):
        user = User.objects.create_user(username='sectionconclusion', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Conclusion Paper', pdf_file=SimpleUploadedFile('section-conclusion.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Conclusion\nThis section closes the discussion and reinforces the main takeaway.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].conclusion, 'This section closes the learning loop by reinforcing the core takeaway.')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature')
    def test_section_learning_service_passes_raw_section_text_to_prompt_builder(self, mock_generate):
        user = User.objects.create_user(username='sectionpayload', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Payload Paper', pdf_file=SimpleUploadedFile('section-payload.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Introduction\nThis paper introduces the problem and the method.\n\nMethods\nThe system is implemented and tested on data.',
            extraction_status='Ready',
        )
        mock_generate.side_effect = [
            '{"sections":[{"title":"Introduction","order":1}]}',
            '{"summary":"A concise explanation","purpose":"It introduces the work","key_points":["The problem is outlined"],"important_terms":["motivation"],"student_note":"Understand the motivation"}',
        ]

        from .section_learning_service import generate_section_learning

        generate_section_learning(paper)

        explanation_call = mock_generate.call_args_list[1]
        self.assertEqual(explanation_call.args[0], 'section_learning')
        self.assertEqual(explanation_call.args[1], 'This paper introduces the problem and the method.')
        self.assertEqual(explanation_call.kwargs['prompt_type'], 'section_explanation')
        self.assertEqual(explanation_call.kwargs['section_title'], 'Introduction')

    def test_prepare_section_learning_text_compacts_large_input(self):
        from .section_learning_service import _prepare_section_text

        large_text = '\n'.join([f'Section {index} content ' + ('word ' * 120) for index in range(20)])

        prepared = _prepare_section_text(large_text)

        self.assertLessEqual(len(prepared), 6000)
        self.assertIn('[truncated]', prepared)

    def test_section_detection_and_single_section_prompt_helpers_exist(self):
        from .prompt_manager import get_section_detection_prompt, get_single_section_explanation_prompt

        detection_prompt = get_section_detection_prompt('Paper introduction and methods section text.')
        section_prompt = get_single_section_explanation_prompt('Introduction', 'This section introduces the problem and outlines the approach.')

        self.assertIn('Return ONLY valid JSON', detection_prompt)
        self.assertIn('"sections"', detection_prompt)
        self.assertIn('"title"', detection_prompt)
        self.assertIn('summary', section_prompt)
        self.assertIn('student_note', section_prompt)
        self.assertNotIn('entire paper', detection_prompt.lower())

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', side_effect=[
        '{"sections":[{"heading":"Introduction","order":1},{"heading":"Methods","order":2}]}',
        '{"summary":"This section introduces the topic and defines the problem clearly.","purpose":"It motivates the work and sets expectations for the reader.","key_points":["The problem is stated clearly.","The gap is explained.","The contribution is framed."],"important_terms":["problem setting","research gap","methodology"],"student_note":"Understand the motivation before reading the technical method."}',
        '{"summary":"This section explains the implementation details and evaluation setup.","purpose":"It shows how the proposed system works and how it was tested.","key_points":["The algorithm is described.","The workflow is mapped out.","The evaluation choices are discussed."],"important_terms":["pipeline","evaluation","dataset"],"student_note":"Connect the method to the results because the evaluation depends on the design choices."}'
    ])
    def test_generate_section_learning_accepts_plain_string_titles(self, mock_generate):
        user = User.objects.create_user(username='sectionstrings', password='Secret123')
        paper = Paper.objects.create(owner=user, title='String Titles Paper', pdf_file=SimpleUploadedFile('string-titles.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Introduction. This paper studies a problem and motivates the approach.\n\nMethods. The system is implemented with a pipeline and evaluated on a dataset.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 2)
        self.assertEqual(sections[0].title, 'Introduction')
        self.assertEqual(sections[1].title, 'Methods')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', side_effect=[
        '{"sections":[{"title":"Introduction","order":1},{"title":"Methods","order":2}]}',
        '{"summary":"This section introduces the topic and defines the problem clearly.","purpose":"It motivates the work and sets expectations for the reader.","key_points":["The problem is stated clearly.","The gap is explained.","The contribution is framed."],"important_terms":["problem setting","research gap","methodology"],"student_note":"Understand the motivation before reading the technical method."}',
        '{"summary":"This section explains the implementation details and evaluation setup.","purpose":"It shows how the proposed system works and how it was tested.","key_points":["The algorithm is described.","The workflow is mapped out.","The evaluation choices are discussed."],"important_terms":["pipeline","evaluation","dataset"],"student_note":"Connect the method to the results because the evaluation depends on the design choices."}'
    ])
    def test_generate_section_learning_uses_detection_then_single_section_explanations(self, mock_generate):
        user = User.objects.create_user(username='sectionpipeline', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Pipeline Paper', pdf_file=SimpleUploadedFile('section-pipeline.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Introduction. This paper studies a problem and motivates the approach.\n\nMethods. The system is implemented with a pipeline and evaluated on a dataset.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 2)
        self.assertEqual(mock_generate.call_count, 3)
        self.assertEqual(sections[0].title, 'Introduction')
        self.assertEqual(sections[1].title, 'Methods')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","order":1,"summary":"A brief overview of the work.","purpose":"It introduces the paper at a high level.","key_points":["The problem is summarized."],"important_terms":["overview"],"student_note":"Understand the main claim first."},{"title":"Introduction","order":2,"summary":"The motivation and context are explained.","purpose":"It frames the problem and the study goal.","key_points":["The gap is stated."],"important_terms":["motivation"],"student_note":"Connect the motivation to the method."},{"title":"Methods","order":3,"summary":"The approach is explained clearly.","purpose":"It describes how the study was conducted.","key_points":["A workflow is outlined."],"important_terms":["methodology"],"student_note":"Follow the workflow carefully."},{"title":"Results","order":4,"summary":"The findings are summarized.","purpose":"It reports what the study found.","key_points":["The outcome is described."],"important_terms":["findings"],"student_note":"Compare the findings to the method."},{"title":"Conclusion","order":5,"summary":"The study is wrapped up.","purpose":"It reinforces the main takeaway.","key_points":["The main lesson is captured."],"important_terms":["takeaway"],"student_note":"Remember the final message."}]}')
    def test_generate_section_learning_uses_extracted_headings_when_available(self, mock_generate):
        user = User.objects.create_user(username='sectionheadings', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Headings Paper', pdf_file=SimpleUploadedFile('section-headings.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Abstract\nThis paper studies a new method.\n\nIntroduction\nThe problem is introduced here.\n\nMethods\nThe implementation details are described here.\n\nResults\nThe findings are presented here.\n\nConclusion\nThe paper is concluded here.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual([section.title for section in sections], ['Abstract', 'Introduction', 'Methods', 'Results', 'Conclusion'])
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Introduction","order":1,"summary":"This section introduces the research problem, explains the gap in prior systems, and motivates the proposed solution by emphasizing the practical constraints and limitations that motivate the study in a concrete way.","purpose":"It establishes why the problem matters, defines the context for the paper, and prepares the reader to understand the technical decisions that follow.","key_points":["The paper identifies a gap in current approaches.","The problem is framed around real-world limitations.","The study motivates a more robust technical design."],"important_terms":["research gap","problem setting","baseline systems"],"student_note":"Understand the motivation and the specific weakness the paper addresses before reading the design section, because the later method depends on this framing."}]}')
    def test_generate_section_learning_persists_and_reuses_database_value(self, mock_generate):
        user = User.objects.create_user(username='sectionuser', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Learning Paper', pdf_file=SimpleUploadedFile('section-learning.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This is a technical paper excerpt for section learning.', extraction_status='Ready')

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)
        self.assertEqual(len(sections), 1)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 1)
        self.assertEqual(PaperSection.objects.get(paper=paper, title='Introduction').section_order, 1)

        sections_again = generate_section_learning(paper)
        self.assertEqual(len(sections_again), 1)
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', side_effect=Exception('Error code: 429 - {"error": {"message": "Rate limit reached for model `llama-3.3-70b-versatile` ..."}}'))
    def test_generate_section_learning_handles_groq_rate_limit_gracefully(self, mock_generate):
        user = User.objects.create_user(username='sectionratelimit', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Rate Limit Paper', pdf_file=SimpleUploadedFile('section-rate-limit.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This is a technical paper excerpt for section learning.', extraction_status='Ready')

        from .section_learning_service import SectionLearningError, generate_section_learning

        with self.assertRaises(SectionLearningError) as exc:
            generate_section_learning(paper)

        self.assertIn('daily token limit', str(exc.exception).lower())
        self.assertIn('rate limit', str(exc.exception).lower())

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Introduction","order":1,"summary":"This section motivates the problem and explains why the work matters.","purpose":"It introduces the research problem and its significance.","key_points":["The paper identifies a practical gap.","The authors define the task clearly."],"important_terms":["problem setting","research gap"],"student_note":"Understand the problem before the method."}]}')
    def test_section_learning_page_renders_generated_sections(self, mock_generate):
        user = User.objects.create_user(username='sectionpage', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Page Paper', pdf_file=SimpleUploadedFile('section-page.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This is a technical paper excerpt for section learning.', extraction_status='Ready')
        PaperSection.objects.create(
            paper=paper,
            title='Introduction',
            section_order=1,
            summary='This section motivates the problem and explains why the work matters.',
            purpose='It introduces the research problem and its significance.',
            key_points=['The paper identifies a practical gap.', 'The authors define the task clearly.'],
            important_terms=['problem setting', 'research gap'],
            student_note='Understand the problem before the method.',
        )

        self.client.force_login(user)
        response = self.client.get(reverse('paper_sections', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Introduction')
        self.assertContains(response, 'This section motivates the problem and explains why the work matters.')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Introduction","order":1,"summary":"This section frames the research problem, shows why prior methods fall short, and motivates the proposed approach by highlighting the limitations of current systems and the practical need for a stronger technical solution.","purpose":"It sets the research context and explains why the work matters, preparing the reader to understand the design decisions that follow in the rest of the paper.","key_points":["The authors describe a gap in existing methods.","The practical limitations of current systems are emphasized.","The study motivates a more robust design."],"important_terms":["research gap","baseline systems","problem setting"],"student_note":"Understand the motivation and the exact weakness the paper addresses before reading the method, because the design choices depend directly on this framing."},{"title":"Methods","order":2,"summary":"The methods section explains the architecture, data flow, and training strategy used to implement the proposed system, connecting each design choice to the research objective and expected behavior.","purpose":"It shows how the proposed solution is operationalized and why the chosen components, assumptions, and procedures are necessary to achieve the stated goal.","key_points":["The method defines the core architecture and pipeline.","Design decisions are tied to the problem statement.","The section explains how the contribution is implemented in practice."],"important_terms":["architecture","training pipeline","objective function"],"student_note":"Focus on how the architecture addresses the problem and which components are essential, since the later results are interpreted through this design."}]}')
    def test_generate_section_learning_force_refresh_replaces_outdated_sections(self, mock_generate):
        user = User.objects.create_user(username='sectionrefresh', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Refresh Paper', pdf_file=SimpleUploadedFile('section-refresh.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper includes an introduction and a methods section with technical details.', extraction_status='Ready')
        PaperSection.objects.create(
            paper=paper,
            title='Introduction',
            section_order=1,
            summary='Short generic intro.',
            purpose='Short generic purpose.',
            key_points=['generic'],
            important_terms=['generic'],
            student_note='Need the basic idea.',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper, force_refresh=True)
        self.assertEqual(len(sections), 2)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 2)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertTrue(any(section.title == 'Methods' for section in sections))

    def test_glossary_prompt_requests_paper_specific_markdown_output(self):
        prompt = build_glossary_prompt('A paper about convolutional networks and transformers.')

        self.assertIn('university teaching assistant', prompt.lower())
        self.assertIn('15–20 glossary entries', prompt)
        self.assertIn('Role in This Paper', prompt)
        self.assertIn('# AI Glossary', prompt)
        self.assertIn('Return Markdown', prompt)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.glossary_service.AIService.generate_feature', return_value='''# AI Glossary\n\n## CNN (Convolutional Neural Network)\n\n### Explanation\nCNNs are neural networks that scan local patterns in data. They are useful for recognizing structure in images and other spatial signals. The key idea is that the model learns filters that respond to repeated features rather than relying on hand-crafted rules.\n\n### Role in This Paper\nThe paper uses CNNs as the core feature extractor for the proposed architecture.\n\n---\n\n## Transformer\n\n### Explanation\nTransformers use attention to connect distant parts of an input sequence. They are especially strong when the model needs to reason about relationships between many tokens.\n\n### Role in This Paper\nThe paper does not explicitly describe how this concept is used.''')
    def test_generate_glossary_persists_entries_and_reuses_database_value(self, mock_generate):
        user = User.objects.create_user(username='glossarygen', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Glossary Generate Paper', pdf_file=SimpleUploadedFile('glossary-generate.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies convolutional networks and transformers for image analysis.', extraction_status='Ready')

        from .glossary_service import generate_glossary

        entries = generate_glossary(paper)

        self.assertEqual(len(entries), 2)
        self.assertEqual(Glossary.objects.filter(paper=paper).count(), 2)
        self.assertEqual(Glossary.objects.get(paper=paper, term='CNN').paper_role, 'The paper uses CNNs as the core feature extractor for the proposed architecture.')
        self.assertEqual(mock_generate.call_count, 1)

        entries_again = generate_glossary(paper)
        self.assertEqual(mock_generate.call_count, 2)
        self.assertEqual(len(entries_again), 2)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.glossary_service.AIService.generate_feature', return_value='''# AI Glossary\n\n## Transformer\n\n### Explanation\nTransformers use attention to connect distant parts of an input sequence.\n\n### Role in This Paper\nThe paper uses transformers in the proposed architecture.''')
    def test_generate_glossary_replaces_existing_entries_when_requested(self, mock_generate):
        user = User.objects.create_user(username='glossaryreplace', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Glossary Replace Paper', pdf_file=SimpleUploadedFile('glossary-replace.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies transformers for sequence modeling.', extraction_status='Ready')
        Glossary.objects.create(paper=paper, term='Old Term', explanation='Old explanation', paper_role='Old role', display_order=1)

        from .glossary_service import generate_glossary

        entries = generate_glossary(paper)

        self.assertEqual(len(entries), 1)
        self.assertEqual(Glossary.objects.filter(paper=paper).count(), 1)
        self.assertEqual(Glossary.objects.get(paper=paper).term, 'Transformer')
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.glossary_service.AIService.generate_feature', return_value='''# AI Glossary\n\n## CNN (Convolutional Neural Network)\n\n### Explanation\nCNNs are neural networks that scan local patterns in data.\n\n### Role in This Paper\nThe paper uses CNNs as the core feature extractor for the proposed architecture.''')
    def test_glossary_page_shows_generate_button_and_generated_cards(self, mock_generate):
        user = User.objects.create_user(username='glossaryview', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Glossary View Paper', pdf_file=SimpleUploadedFile('glossary-view.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies convolutional networks for image analysis.', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_glossary', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate Glossary')

        response = self.client.post(reverse('paper_glossary', args=[paper.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CNN')
        self.assertContains(response, 'Role in This Paper')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.flashcard_service.AIService.generate_feature', return_value='{"flashcards":[{"question":"What is the research goal?","answer":"The paper focuses on a specific task described in the introduction.","paper_context":"The introduction defines the main objective and explains why the task is important.","importance":["Frames the study","Connects methods to results"],"category":"Research Problem","difficulty":"Easy"}]}')
    def test_generate_flashcards_persists_and_reuses_database_value(self, mock_generate_feature):
        user = User.objects.create_user(username='flashcardgen', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Flashcard Generate Paper', pdf_file=SimpleUploadedFile('flashcards.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        cards = generate_flashcards(paper)
        self.assertEqual(len(cards), 1)
        self.assertEqual(Flashcard.objects.filter(paper=paper).count(), 1)
        self.assertEqual(cards[0].category, 'Research Problem')
        self.assertEqual(mock_generate_feature.call_count, 1)

        cards_again = generate_flashcards(paper)
        self.assertEqual(len(cards_again), 1)
        self.assertEqual(mock_generate_feature.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    def test_flashcards_page_shows_generate_button_and_can_generate_cards(self):
        user = User.objects.create_user(username='flashcardview', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Flashcard View Paper', pdf_file=SimpleUploadedFile('flashcards-view.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a task and describes methods and results.', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_flashcards', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate Flashcards')

        response = self.client.post(reverse('paper_flashcards', args=[paper.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flashcards generated successfully.')
        self.assertTrue(Flashcard.objects.filter(paper=paper).exists())

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"' + ('Easy' if index <= 4 else 'Medium' if index <= 8 else 'Hard') + '","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 11)
    ]) + ']}')
    def test_generate_quiz_persists_questions_and_reuses_database_value(self, mock_generate_feature):
        user = User.objects.create_user(username='quizgen', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Generate Paper', pdf_file=SimpleUploadedFile('quiz-generate.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a novel method and reports results from a detailed experiment.', extraction_status='Ready')

        questions = generate_quiz(paper)

        self.assertEqual(len(questions), 10)
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(questions[0].difficulty, 'Easy')

        questions_again = generate_quiz(paper)
        self.assertEqual(len(questions_again), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    def test_quiz_page_resets_previous_answers_when_starting_over(self):
        user = User.objects.create_user(username='quizreset', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Reset Paper', pdf_file=SimpleUploadedFile('quiz-reset.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='The paper covers a research problem and a proposed solution.', extraction_status='Ready')
        QuizQuestion.objects.create(paper=paper, question='First question', option_a='A', option_b='B', option_c='C', option_d='D', correct_answer='A', explanation='Explanation', display_order=1)
        QuizQuestion.objects.create(paper=paper, question='Second question', option_a='A', option_b='B', option_c='C', option_d='D', correct_answer='B', explanation='Explanation', display_order=2)

        self.client.force_login(user)
        session = self.client.session
        session[f'quiz_answers_{paper.id}'] = {'0': 'A'}
        session.save()

        response = self.client.post(reverse('paper_quiz', args=[paper.pk]), {'action': 'generate'}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'checked')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"' + ('Easy' if index <= 4 else 'Medium' if index <= 8 else 'Hard') + '","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 11)
    ]) + ']}')
    def test_quiz_page_shows_generate_button_and_can_generate_quiz(self, mock_generate_feature):
        user = User.objects.create_user(username='quizview', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz View Paper', pdf_file=SimpleUploadedFile('quiz-view.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='The paper discusses a research problem and an approach designed to solve it.', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_quiz', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate Quiz')

        response = self.client.post(reverse('paper_quiz', args=[paper.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Quiz generated successfully.')
        self.assertTrue(QuizQuestion.objects.filter(paper=paper).exists())

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.flashcard_service.AIService.generate_feature', return_value='{"flashcards":[{"question":"What is the research goal?","answer":"The paper focuses on a specific task described in the introduction.","paper_context":"The introduction defines the main objective and explains why the task is important.","importance":["Frames the study","Connects methods to results"],"category":"Research Problem","difficulty":"Easy"}]}')
    def test_generate_flashcards_fails_when_missing_extracted_text(self, mock_generate_feature):
        user = User.objects.create_user(username='flashcardfail', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Flashcard Fail Paper', pdf_file=SimpleUploadedFile('flashcards-fail.pdf', b'%PDF-1.4\n', content_type='application/pdf'))

        with self.assertRaises(FlashcardGenerationError):
            generate_flashcards(paper)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', return_value='{"technical_explanation":"# Technical Explanation\\n\\n## Overall Technical Architecture\\n\\n' + ('This is a complete technical lecture note. ' * 80) + '\\n\\n## Model Architecture\\n\\nThis section teaches the background concepts needed to understand the paper. ","beginner_explanation":"A simple explanation","key_contributions":["Important contribution"],"key_concepts":["Core concept"],"reading_difficulty":{"level":"Intermediate","reason":"A bit technical"},"glossary":[],"flashcards":[],"viva_questions":[]}')
    def test_generate_technical_explanation_persists_once_and_reuses_database_value(self, mock_generate):
        user = User.objects.create_user(username='technicalgen', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Technical Generate Paper', pdf_file=SimpleUploadedFile('technical-generate.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This is a technical paper excerpt for generation.', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.post(reverse('paper_technical', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Technical Explanation')
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertIn('Overall Technical Architecture', analysis.technical_explanation)
        self.assertEqual(mock_generate.call_count, 1)

        response_refresh = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertEqual(response_refresh.status_code, 200)
        self.assertContains(response_refresh, 'Overall Technical Architecture')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate')
    def test_generate_technical_explanation_requests_fresh_api_output_every_time(self, mock_generate):
        user = User.objects.create_user(username='technicalrefresh', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Technical Refresh Paper', pdf_file=SimpleUploadedFile('technical-refresh.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This is a technical paper excerpt for generation.', extraction_status='Ready')
        AIAnalysis.objects.create(
            paper=paper,
            technical_explanation='# Technical Explanation\n\n## Overall Technical Architecture\n\nThis system studies a new method.' * 200,
            analysis_status='Ready',
            ai_model='mock',
        )

        long_response = '{"technical_explanation":"' + ('This is a full technical lecture paragraph. ' * 90) + '","beginner_explanation":"A simple explanation","key_contributions":["Important contribution"],"key_concepts":["Core concept"],"reading_difficulty":{"level":"Intermediate","reason":"A bit technical"},"glossary":[],"flashcards":[],"viva_questions":[]}'
        bad_response = '```json\n{\x1b"technical_explanation": "# Technical Explanation\\n\\n## Research Objective\\n\\nThis is invalid because the control character is embedded."}\n```'
        mock_generate.side_effect = [bad_response, long_response]

        self.client.force_login(user)
        response = self.client.post(reverse('paper_technical', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_generate.call_count, 2)
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertIn('This is a full technical lecture paragraph', analysis.technical_explanation)

    @override_settings(AI_PROVIDER='mock')
    def test_start_learning_extracts_text_and_marks_paper_ready(self):
        user = User.objects.create_user(username='learner', password='Secret123')
        buffer = BytesIO()
        pdf_canvas = canvas.Canvas(buffer)
        pdf_canvas.drawString(72, 720, 'ResearchMate learning preparation test')
        pdf_canvas.save()
        pdf_bytes = buffer.getvalue()

        paper = Paper.objects.create(
            owner=user,
            title='Prepared Paper',
            pdf_file=SimpleUploadedFile('prepared.pdf', pdf_bytes, content_type='application/pdf'),
        )

        self.client.force_login(user)
        response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        content = PaperContent.objects.get(paper=paper)
        self.assertEqual(content.extraction_status, 'Ready')
        self.assertIn('ResearchMate', content.extracted_text)
        self.assertEqual(content.page_count, 1)
        self.assertContains(response, 'Paper is prepared for AI learning')

    @override_settings(AI_PROVIDER='mock')
    def test_start_learning_only_generates_beginner_content_from_initial_pipeline(self):
        user = User.objects.create_user(username='mocklearner', password='Secret123')
        buffer = BytesIO()
        pdf_canvas = canvas.Canvas(buffer)
        pdf_canvas.drawString(72, 720, 'Mock learning pipeline content')
        pdf_canvas.save()
        pdf_bytes = buffer.getvalue()

        paper = Paper.objects.create(
            owner=user,
            title='Mock Learning Paper',
            pdf_file=SimpleUploadedFile('mock.pdf', pdf_bytes, content_type='application/pdf'),
        )

        self.client.force_login(user)
        response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AIAnalysis.objects.filter(paper=paper).exists())
        self.assertFalse(Glossary.objects.filter(paper=paper).exists())
        self.assertFalse(Flashcard.objects.filter(paper=paper).exists())
        self.assertFalse(QuizQuestion.objects.filter(paper=paper).exists())
        self.assertFalse(VivaQuestion.objects.filter(paper=paper).exists())
        self.assertTrue(LearningProgress.objects.filter(paper=paper).exists())

        progress = paper.learning_progress
        self.assertTrue(progress.beginner_completed)
        self.assertFalse(progress.glossary_completed)
        self.assertFalse(progress.flashcards_completed)
        self.assertFalse(progress.quiz_completed)
        self.assertFalse(progress.viva_completed)

    @override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
    @patch('papers.ai_providers.GroqProvider.generate', return_value='{"beginner_explanation":"A simple explanation","technical_explanation":"A technical explanation","key_contributions":["Important contribution"],"key_concepts":["Core concept"],"reading_difficulty":{"level":"Intermediate","reason":"Needs background knowledge"},"section_learning":[{"section":"Introduction","summary":"Read the intro first"}],"glossary":[{"term":"Neuron","simple_explanation":"A nerve cell","technical_explanation":"Specialized cell transmitting signals","example":"Neurons communicate through synapses"}],"flashcards":[{"question":"What is a neuron?","answer":"A nerve cell"}],"quiz_questions":[{"question":"What is a neuron?","options":["A","B","C","D"],"correct_answer":1,"difficulty":"Easy","explanation":"It is a nerve cell."}],"viva_questions":[{"question":"What is the main contribution?","suggested_answer":"It advances the field","follow_up_question":"Why is it significant?"}]}')
    def test_beginner_generation_does_not_create_other_learning_modules(self, mock_generate):
        user = User.objects.create_user(username='groqlearner', password='Secret123')
        buffer = BytesIO()
        pdf_canvas = canvas.Canvas(buffer)
        pdf_canvas.drawString(72, 720, 'Groq learning pipeline content')
        pdf_canvas.save()
        pdf_bytes = buffer.getvalue()

        paper = Paper.objects.create(
            owner=user,
            title='Groq Learning Paper',
            pdf_file=SimpleUploadedFile('groq.pdf', pdf_bytes, content_type='application/pdf'),
        )

        self.client.force_login(user)
        response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.analysis_status, 'Ready')
        self.assertEqual(analysis.ai_model, 'groq')
        self.assertEqual(analysis.beginner_explanation, 'A simple explanation')
        self.assertFalse(Glossary.objects.filter(paper=paper).exists())
        self.assertFalse(Flashcard.objects.filter(paper=paper).exists())
        self.assertFalse(QuizQuestion.objects.filter(paper=paper).exists())
        self.assertFalse(VivaQuestion.objects.filter(paper=paper).exists())

        progress = paper.learning_progress
        self.assertTrue(progress.beginner_completed)
        self.assertFalse(progress.glossary_completed)
        self.assertFalse(progress.flashcards_completed)
        self.assertFalse(progress.quiz_completed)
        self.assertFalse(progress.viva_completed)

    @override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
    @patch('papers.ai_providers.GroqProvider.generate', side_effect=RuntimeError('Groq unavailable'))
    def test_start_learning_keeps_existing_analysis_when_groq_fails(self, mock_generate):
        user = User.objects.create_user(username='groqfailure', password='Secret123')
        buffer = BytesIO()
        pdf_canvas = canvas.Canvas(buffer)
        pdf_canvas.drawString(72, 720, 'Groq failure handling content')
        pdf_canvas.save()
        pdf_bytes = buffer.getvalue()

        paper = Paper.objects.create(
            owner=user,
            title='Groq Failure Paper',
            pdf_file=SimpleUploadedFile('groq-failure.pdf', pdf_bytes, content_type='application/pdf'),
        )
        existing_analysis = AIAnalysis.objects.create(paper=paper, overview='Existing overview', analysis_status='Ready')

        self.client.force_login(user)
        response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AI analysis could not be completed.')
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.overview, existing_analysis.overview)
        self.assertEqual(analysis.analysis_status, 'Failed')

    def test_retry_generation_reuses_existing_content_and_shows_retry_button(self):
        user = User.objects.create_user(username='retryuser', password='Secret123')
        paper = Paper.objects.create(
            owner=user,
            title='Retry Paper',
            pdf_file=SimpleUploadedFile('retry.pdf', b'%PDF-1.4\n', content_type='application/pdf'),
        )
        PaperContent.objects.create(paper=paper, extracted_text='Existing extracted text', extraction_status='Ready')
        AIAnalysis.objects.create(paper=paper, analysis_status='Failed', analysis_error='Rate limit exceeded')

        self.client.force_login(user)
        with patch('papers.views.extract_pdf_content', side_effect=AssertionError('should not extract again')), patch('papers.views.process_mock_ai', return_value=SimpleNamespace(analysis_status='Failed')):
            response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Retry AI Generation')
        self.assertNotContains(response, 'Traceback')

    def test_authentication_errors_with_rate_limit_words_do_not_show_usage_limit_message(self):
        analysis = SimpleNamespace(
            analysis_error='Authentication failed. The API key is invalid and the provider also mentioned rate limit exceeded.'
        )

        self.assertEqual(
            _get_user_facing_error_message(analysis),
            'AI analysis could not be completed. Authentication with the AI provider failed. Please check the API configuration.'
        )

    def test_non_rate_limit_provider_errors_do_not_show_usage_limit_message(self):
        analysis = SimpleNamespace(analysis_error='The provider returned an unexpected error. Please try again later.')

        self.assertEqual(
            _get_user_facing_error_message(analysis),
            'AI analysis could not be completed. Please try again later.'
        )

    def test_failed_generation_page_shows_single_clear_error_banner(self):
        user = User.objects.create_user(username='errorbanner', password='Secret123')
        paper = Paper.objects.create(
            owner=user,
            title='Error Banner Paper',
            pdf_file=SimpleUploadedFile('banner.pdf', b'%PDF-1.4\n', content_type='application/pdf'),
        )
        AIAnalysis.objects.create(paper=paper, analysis_status='Failed', analysis_error='Rate limit exceeded')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'We could not complete AI generation.')
        self.assertContains(response, 'AI analysis could not be completed')
        self.assertNotContains(response, 'AI generation could not be completed.')

    def test_validate_json_response_ignores_control_characters_before_parsing(self):
        raw_response = '```json\n{\x1b"technical_explanation": "# Technical Explanation\\n\\n## Research Objective\\n\\nThis is a valid explanation."}\n```'

        valid, payload, error_message = validate_json_response(raw_response)

        self.assertTrue(valid)
        self.assertEqual(payload['technical_explanation'], '# Technical Explanation\n\n## Research Objective\n\nThis is a valid explanation.')
        self.assertEqual(error_message, '')

    @override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
    def test_regenerating_failed_analysis_resets_state_before_new_provider_request(self):
        user = User.objects.create_user(username='regenstate', password='Secret123')
        paper = Paper.objects.create(
            owner=user,
            title='Regeneration Paper',
            pdf_file=SimpleUploadedFile('regen.pdf', b'%PDF-1.4\n', content_type='application/pdf'),
        )
        PaperContent.objects.create(paper=paper, extracted_text='Paper content for regeneration', extraction_status='Ready')
        analysis = AIAnalysis.objects.create(paper=paper, analysis_status='Failed', analysis_error='old error', raw_response='stale response')

        def fake_generate(prompt):
            refreshed = AIAnalysis.objects.get(pk=analysis.pk)
            self.assertEqual(refreshed.analysis_status, 'Processing')
            self.assertEqual(refreshed.analysis_error, '')
            self.assertEqual(refreshed.raw_response, '')
            return '{"beginner_explanation":"Fresh explanation","technical_explanation":"Fresh technical explanation","key_contributions":["Fresh contribution"],"key_concepts":["Fresh concept"],"reading_difficulty":{"level":"Intermediate","reason":"Refreshed"},"glossary":[],"flashcards":[],"viva_questions":[]}'

        with patch('papers.ai_providers.GroqProvider.generate', side_effect=fake_generate):
            self.client.force_login(user)
            response = self.client.post(reverse('start_learning', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        refreshed = AIAnalysis.objects.get(pk=analysis.pk)
        self.assertEqual(refreshed.analysis_status, 'Ready')
        self.assertEqual(refreshed.analysis_error, '')

    def test_ai_foundation_relationships_are_available(self):
        user = User.objects.create_user(username='foundationuser', password='Secret123')
        paper = Paper.objects.create(
            owner=user,
            title='Foundation Paper',
            pdf_file=SimpleUploadedFile('foundation.pdf', b'%PDF-1.4\n', content_type='application/pdf'),
        )

        analysis = AIAnalysis.objects.create(paper=paper, overview='A placeholder overview')
        progress = LearningProgress.objects.create(paper=paper)

        self.assertEqual(analysis.paper, paper)
        self.assertEqual(progress.paper, paper)
        self.assertEqual(paper.ai_analysis, analysis)
        self.assertEqual(paper.learning_progress, progress)
