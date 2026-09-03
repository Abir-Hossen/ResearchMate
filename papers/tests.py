import os
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from reportlab.pdfgen import canvas

from .models import AIAnalysis, Flashcard, Glossary, LearningProgress, Paper, PaperContent, PaperSection, QuizAttempt, QuizQuestion, Review, VivaQuestion
from subscriptions.models import SubscriptionPlan, UserSubscription
from .prompts.beginner import build_beginner_prompt
from .prompts.glossary import build_glossary_prompt
from .prompts.revision_notes import build_revision_notes_prompt
from .prompts.section_learning import build_section_learning_prompt
from .prompts.technical import build_technical_prompt
from .response_validator import validate_json_response
from .services import _get_user_facing_error_message
from .technical_service import TechnicalExplanationError, _clean_technical_markdown
from .flashcard_service import FlashcardGenerationError, generate_flashcards
from .quiz_service import QuizGenerationError, generate_quiz


def _create_premium_subscription(user, days=7):
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


class GroqProviderTests(TestCase):
    def test_groq_provider_requests_json_object_response(self):
        from .ai_providers import GroqProvider

        provider = GroqProvider.__new__(GroqProvider)
        provider.model_name = 'openai/gpt-oss-120b'
        provider.last_usage = None
        provider.last_response_time = None
        provider.last_error_details = None
        provider.groq_module = SimpleNamespace()

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"beginner_explanation":"works"}'))],
            usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        )

        provider.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=Mock(return_value=mock_response))
            )
        )

        result = provider.generate('prompt text')

        self.assertEqual(result, '{"beginner_explanation":"works"}')
        provider.client.chat.completions.create.assert_called_once_with(
            model='openai/gpt-oss-120b',
            messages=[{'role': 'user', 'content': 'prompt text'}],
            temperature=0.0,
            max_completion_tokens=4000,
        )


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
        self.assertIn('"key_contributions"', prompt)
        self.assertIn('"key_concepts"', prompt)
        self.assertIn('"reading_difficulty"', prompt)
        self.assertNotIn('"technical_explanation"', prompt)
        self.assertNotIn('"glossary"', prompt)
        self.assertNotIn('"flashcards"', prompt)
        self.assertNotIn('"quiz_questions"', prompt)
        self.assertNotIn('"viva_questions"', prompt)

    def test_technical_prompt_requests_structured_markdown_sections(self):
        long_text = ' '.join(['paper'] * 5000)
        prompt = build_beginner_prompt(long_text)

        self.assertIn('"beginner_explanation"', prompt)
        self.assertNotIn('"technical_explanation"', prompt)
        self.assertNotIn('"glossary"', prompt)
        self.assertNotIn('"flashcards"', prompt)
        self.assertNotIn('"quiz_questions"', prompt)
        self.assertNotIn('"viva_questions"', prompt)
        self.assertIn('600-800 words', prompt)
        self.assertIn('Paper text:', prompt)
        self.assertLess(len(prompt), 12000)

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
        _create_premium_subscription(user)
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
        _create_premium_subscription(user)
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
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Technical Button Paper', pdf_file=SimpleUploadedFile('technical-button.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='Technical button extraction content', extraction_status='Ready')

        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate Technical Explanation')
        self.assertNotContains(response, 'Run Start Learning to generate a technical explanation.')

    def test_section_learning_prompt_requests_section_json_schema(self):
        prompt = build_section_learning_prompt('Abstract\nThis paper introduces X.\n\nIntroduction\nWe study Y.\n\nMethods\nWe use Z.\n\nResults\nWe found W.\n\nConclusion\nWe conclude V.')

        self.assertIn('"sections"', prompt)
        self.assertIn('"title"', prompt)
        self.assertIn('"explanation"', prompt)
        self.assertIn('60-90 word', prompt)
        self.assertIn('expert academic reading tutor', prompt)
        self.assertIn('Abstract', prompt)
        self.assertIn('Introduction', prompt)
        self.assertIn('Related Work', prompt)
        self.assertIn('Methodology', prompt)
        self.assertIn('Results and Discussion', prompt)
        self.assertIn('Conclusion', prompt)
        self.assertNotIn('"summary"', prompt)

    def test_section_learning_prompt_compacts_large_section_text(self):
        long_text = ' '.join(['token'] * 4000)

        prompt = build_section_learning_prompt(long_text)

        self.assertIn('Labeled paper sections:', prompt)
        self.assertIn('[truncated]', prompt)
        self.assertLess(len(prompt), 25000)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem, explains the gap in prior systems, and motivates the proposed solution by emphasizing the practical constraints and limitations that motivate the study in a concrete way."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"The approach is explained clearly."},{"title":"Results and Discussion","explanation":"The findings are summarized."},{"title":"Conclusion","explanation":"The study is wrapped up."}]}')
    def test_generate_section_learning_persists_explanation(self, mock_generate):
        user = User.objects.create_user(username='sectionconclusion', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Conclusion Paper', pdf_file=SimpleUploadedFile('section-conclusion.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Conclusion\nThis section closes the discussion and reinforces the main takeaway.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[5].title, 'Conclusion')
        self.assertIn('The study is wrapped up.', sections[5].summary)
        self.assertEqual(mock_generate.call_count, 1)

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
        mock_generate.return_value = '{"sections":[{"title":"Abstract","explanation":"A brief overview."},{"title":"Introduction","explanation":"A concise explanation."},{"title":"Related Work","explanation":"Prior work is reviewed."},{"title":"Methodology","explanation":"The approach is explained."},{"title":"Results and Discussion","explanation":"The findings are summarized."},{"title":"Conclusion","explanation":"The study is wrapped up."}]}'

        from .section_learning_service import generate_section_learning

        generate_section_learning(paper)

        first_call = mock_generate.call_args_list[0]
        self.assertEqual(first_call.args[0], 'section_learning')
        sent_text = first_call.args[1]
        self.assertIn('Introduction:', sent_text)
        self.assertIn('This paper introduces the problem and the method', sent_text)
        self.assertIn('Methodology:', sent_text)
        self.assertEqual(first_call.kwargs['prompt_type'], 'section_detection')

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

        self.assertIn('"sections"', detection_prompt)
        self.assertIn('"title"', detection_prompt)
        self.assertIn('"explanation"', detection_prompt)
        self.assertIn('60-90 word', detection_prompt)
        self.assertIn('expert academic reading tutor', detection_prompt)
        self.assertNotIn('entire paper', detection_prompt.lower())

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivates the approach."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"This section presents the experimental results and findings."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
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

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[0].title, 'Abstract')
        self.assertEqual(sections[1].title, 'Introduction')
        self.assertEqual(sections[2].title, 'Related Work')
        self.assertEqual(sections[3].title, 'Methodology')
        self.assertEqual(sections[4].title, 'Results and Discussion')
        self.assertEqual(sections[5].title, 'Conclusion')
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivates the approach."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"This section presents the experimental results and findings."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
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

        self.assertEqual(len(sections), 6)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(sections[0].title, 'Abstract')
        self.assertEqual(sections[1].title, 'Introduction')
        self.assertEqual(sections[5].title, 'Conclusion')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"The motivation and context are explained."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"The approach is explained clearly."},{"title":"Results and Discussion","explanation":"The findings are summarized."},{"title":"Conclusion","explanation":"The study is wrapped up."}]}')
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

        self.assertEqual(len(sections), 6)
        self.assertEqual([s.title for s in sections], ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results and Discussion', 'Conclusion'])
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem, explains the gap in prior systems, and motivates the proposed solution by emphasizing the practical constraints and limitations that motivate the study in a concrete way."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"The approach is explained clearly."},{"title":"Results and Discussion","explanation":"The findings are summarized."},{"title":"Conclusion","explanation":"The study is wrapped up."}]}')
    def test_generate_section_learning_persists_and_reuses_database_value(self, mock_generate):
        user = User.objects.create_user(username='sectionuser', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Learning Paper', pdf_file=SimpleUploadedFile('section-learning.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='Introduction\nThis is a technical paper excerpt for section learning.', extraction_status='Ready')

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)
        self.assertEqual(len(sections), 6)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 6)
        intro_section = PaperSection.objects.get(paper=paper, title='Introduction')
        self.assertIn('research problem', intro_section.summary)
        self.assertIn('motivates the proposed solution', intro_section.summary)

        sections_again = generate_section_learning(paper)
        self.assertEqual(len(sections_again), 6)
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
        _create_premium_subscription(user)
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
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section motivates the problem and explains why the work matters."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"This section presents the results."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_force_refresh_replaces_outdated_sections(self, mock_generate):
        user = User.objects.create_user(username='sectionrefresh', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Section Refresh Paper', pdf_file=SimpleUploadedFile('section-refresh.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='Introduction\nThis paper includes an introduction and a methods section with technical details.\n\nMethods\nThe methods section explains the architecture.', extraction_status='Ready')
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
        self.assertEqual(len(sections), 6)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 6)
        self.assertEqual(mock_generate.call_count, 1)
        self.assertTrue(any(section.title == 'Methodology' for section in sections))

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the problem and motivation."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"A single results section explaining the experimental outcomes and key metrics reported in the paper."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_deduplicates_repeated_sections(self, mock_generate):
        """Test that duplicate section headings are deduplicated (only first occurrence used)."""
        user = User.objects.create_user(username='sectiondedup', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Dedup Test Paper', pdf_file=SimpleUploadedFile('dedup.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        # Text with "Results" appearing twice
        text_with_duplicates = '''
Introduction
The problem statement and motivation.

Methods
The proposed approach and technical details.

Results
First set of results and findings.

Results
Additional results in a separate section.
        '''
        PaperContent.objects.create(paper=paper, extracted_text=text_with_duplicates, extraction_status='Ready')

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)
        # Should have exactly 6 fixed sections
        self.assertEqual(len(sections), 6)
        self.assertEqual(PaperSection.objects.filter(paper=paper).count(), 6)
        # Should only generate 1 AI request (whole paper analysis)
        self.assertEqual(mock_generate.call_count, 1)
        # Verify section titles are unique
        section_titles = [s.title for s in sections]
        self.assertEqual(len(section_titles), len(set(title.lower() for title in section_titles)))

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"This section provides a brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."},{"title":"Related Work","explanation":"This section reviews related work and identifies the research gap."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"This section presents the experimental results and findings."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_detects_standard_paper_sections(self, mock_generate):
        user = User.objects.create_user(username='sectionstandard', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Standard Sections Paper', pdf_file=SimpleUploadedFile('standard.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Abstract\nThis is the abstract.\n\nIntroduction\nThis is the introduction.\n\nRelated Work\nThis is related work.\n\nMethodology\nThis is methodology.\n\nResults\nThese are results.\n\nConclusion\nThis is conclusion.\n\nLimitations\nThese are limitations.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual([s.title for s in sections], ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results and Discussion', 'Conclusion'])
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"This section presents the experimental results and findings."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_detects_numbered_headings(self, mock_generate):
        user = User.objects.create_user(username='sectionnumbered', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Numbered Sections Paper', pdf_file=SimpleUploadedFile('numbered.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='1. Introduction\nThis is the introduction.\n\n2. Methodology\nThis is methodology.\n\n3. Results\nThese are results.\n\n4. Conclusion\nThis is conclusion.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual([s.title for s in sections], ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results and Discussion', 'Conclusion'])
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"A single results section explaining the experimental outcomes and key metrics reported in the paper."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_normalizes_duplicate_heading_patterns(self, mock_generate):
        user = User.objects.create_user(username='sectionnormalize', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Normalize Sections Paper', pdf_file=SimpleUploadedFile('normalize.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='4 Results\nFirst set of results and findings.\n\nResults\nAdditional results in a separate section.\n\nRESULTS\nFinal results summary.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[4].title, 'Results and Discussion')
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach."},{"title":"Results and Discussion","explanation":"The findings are summarized."},{"title":"Conclusion","explanation":"The study is wrapped up."}]}')
    def test_generate_section_learning_fallback_main_content_when_no_headings(self, mock_generate):
        user = User.objects.create_user(username='sectionmaincontent', password='Secret123')
        paper = Paper.objects.create(owner=user, title='No Headings Paper', pdf_file=SimpleUploadedFile('noheadings.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='This is just plain text without any recognizable section headings. It discusses machine learning and image classification.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[0].title, 'Abstract')
        self.assertEqual(sections[5].title, 'Conclusion')
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."},{"title":"Related Work","explanation":"Prior work is reviewed here."},{"title":"Methodology","explanation":"This section describes the methodology and experimental approach in detail."},{"title":"Results and Discussion","explanation":"This section presents the results."},{"title":"Conclusion","explanation":"This section concludes the paper and discusses implications."}]}')
    def test_generate_section_learning_truncates_long_section_text(self, mock_generate):
        user = User.objects.create_user(username='sectiontruncate', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Truncate Paper', pdf_file=SimpleUploadedFile('truncate.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        long_text = 'Methodology\n' + ('word ' * 12000) + '\n\nResults\nsome results'
        PaperContent.objects.create(paper=paper, extracted_text=long_text, extraction_status='Ready')

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[3].title, 'Methodology')
        self.assertEqual(mock_generate.call_count, 1)
        sent_text = mock_generate.call_args.args[1]
        self.assertIn('Methodology:', sent_text)
        self.assertIn('Results and Discussion:', sent_text)
        self.assertLess(sent_text.count('word'), 200)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."}]}')
    def test_generate_section_learning_combined_results_discussion_fallback(self, mock_generate):
        user = User.objects.create_user(username='sectioncombined', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Combined Results Paper', pdf_file=SimpleUploadedFile('combined.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='Abstract\nThis is the abstract.\n\nIntroduction\nThis is the introduction.\n\n3. Methodology\nThis is methodology.\n\n4. Results\nThese are results.\n\n5. Discussion\nThis is discussion.\n\n6. Conclusion\nThis is conclusion.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        titles = [s.title for s in sections]
        self.assertEqual(titles, ['Abstract', 'Introduction', 'Related Work', 'Methodology', 'Results and Discussion', 'Conclusion'])
        self.assertIn('results', sections[4].summary.lower())
        self.assertIn('discussion', sections[4].summary.lower())
        self.assertEqual(mock_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.section_learning_service.AIService.generate_feature', return_value='{"sections":[{"title":"Abstract","explanation":"A brief overview of the work."},{"title":"Introduction","explanation":"This section introduces the research problem and motivation."}]}')
    def test_generate_section_learning_numbered_headings_fallback(self, mock_generate):
        user = User.objects.create_user(username='sectionnumberedfallback', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Numbered Fallback Paper', pdf_file=SimpleUploadedFile('numbered-fallback.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(
            paper=paper,
            extracted_text='1. Introduction\nThis is the introduction.\n\n2. Methodology\nThis is methodology.\n\n3. Results\nThese are results.\n\n4. Discussion\nThis is discussion.\n\n5. Conclusion\nThis is conclusion.',
            extraction_status='Ready',
        )

        from .section_learning_service import generate_section_learning

        sections = generate_section_learning(paper)

        self.assertEqual(len(sections), 6)
        self.assertEqual(sections[3].title, 'Methodology')
        self.assertIn('methodology', sections[3].summary.lower())
        self.assertEqual(sections[4].title, 'Results and Discussion')
        self.assertIn('results', sections[4].summary.lower())
        self.assertIn('discussion', sections[4].summary.lower())
        self.assertEqual(mock_generate.call_count, 1)

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
        _create_premium_subscription(user)
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
        _create_premium_subscription(user)
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
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"' + ('Easy' if index <= 3 else 'Medium' if index <= 7 else 'Hard') + '","explanation":"Explanation ' + str(index) + '"}'
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
        mock_generate_feature.assert_called_once_with('quiz', 'This paper studies a novel method and reports results from a detailed experiment.', max_completion_tokens=2500)

        questions_again = generate_quiz(paper)
        self.assertEqual(len(questions_again), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    def test_quiz_page_resets_previous_answers_when_starting_over(self):
        user = User.objects.create_user(username='quizreset', password='Secret123')
        _create_premium_subscription(user)
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
    @patch('papers.ai_providers.MockProvider.generate', return_value='not valid json')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='not valid json')
    def test_generate_quiz_raises_on_malformed_json(self, mock_generate_feature, mock_provider_generate):
        user = User.objects.create_user(username='quizmalformed', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Malformed Paper', pdf_file=SimpleUploadedFile('quiz-malformed.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('invalid quiz response', str(exc.exception).lower())
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', return_value='{"quiz_questions":[]}')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[]}')
    def test_generate_quiz_raises_on_empty_quiz_list(self, mock_generate_feature, mock_provider_generate):
        user = User.objects.create_user(username='quizempty', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Empty Paper', pdf_file=SimpleUploadedFile('quiz-empty.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('incomplete quiz response', str(exc.exception).lower())
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 4)
    ]) + ']}')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 4)
    ]) + ']}')
    def test_generate_quiz_raises_on_fewer_than_five_questions(self, mock_generate_feature, mock_provider_generate):
        user = User.objects.create_user(username='quizfew', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Few Paper', pdf_file=SimpleUploadedFile('quiz-few.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('incomplete quiz response', str(exc.exception).lower())
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 13)
    ]) + ']}')
    def test_generate_quiz_truncates_more_than_ten_questions(self, mock_generate_feature):
        user = User.objects.create_user(username='quizmany', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Many Paper', pdf_file=SimpleUploadedFile('quiz-many.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        questions = generate_quiz(paper)

        self.assertEqual(len(questions), 10)
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"Z","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 6)
    ]) + ']}')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"Z","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 6)
    ]) + ']}')
    def test_generate_quiz_raises_on_invalid_correct_answer(self, mock_generate_feature, mock_provider_generate):
        user = User.objects.create_user(username='quizwrongans', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Wrong Ans Paper', pdf_file=SimpleUploadedFile('quiz-wrongans.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('incomplete quiz response', str(exc.exception).lower())
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Duplicate question","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 1"}',
        '{"question":"Duplicate question","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 2"}',
        '{"question":"Unique question 1","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 3"}',
        '{"question":"Unique question 2","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 4"}',
        '{"question":"Unique question 3","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 5"}',
    ]) + ']}')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Duplicate question","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 1"}',
        '{"question":"Duplicate question","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 2"}',
        '{"question":"Unique question 1","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 3"}',
        '{"question":"Unique question 2","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 4"}',
        '{"question":"Unique question 3","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"Easy","explanation":"Explanation 5"}',
    ]) + ']}')
    def test_generate_quiz_rejects_duplicate_questions(self, mock_generate_feature, mock_provider_generate):
        user = User.objects.create_user(username='quizdup', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Dup Paper', pdf_file=SimpleUploadedFile('quiz-dup.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('incomplete quiz response', str(exc.exception).lower())
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 0)
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider_generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', side_effect=Exception('Error code: 429 - {"error": {"message": "Rate limit reached for model."}}'))
    def test_generate_quiz_handles_rate_limit_gracefully(self, mock_generate_feature):
        user = User.objects.create_user(username='quizratelimit', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Rate Limit Paper', pdf_file=SimpleUploadedFile('quiz-ratelimit.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        with self.assertRaises(QuizGenerationError) as exc:
            generate_quiz(paper)

        self.assertIn('usage limit', str(exc.exception).lower())
        self.assertIn('try again later', str(exc.exception).lower())

    def test_generate_quiz_truncates_long_paper_text(self):
        from .quiz_service import _prepare_quiz_text

        long_text = 'word ' * 2000
        prepared = _prepare_quiz_text(long_text)

        self.assertLessEqual(len(prepared), 5000)
        self.assertIn('[truncated]', prepared)

    def test_generate_quiz_keeps_short_paper_text_intact(self):
        from .quiz_service import _prepare_quiz_text

        short_text = 'This is a short paper text about a novel method.'
        prepared = _prepare_quiz_text(short_text)

        self.assertEqual(prepared, short_text)
        self.assertNotIn('[truncated]', prepared)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', side_effect=[
        '{"quiz_questions":[' + ','.join([
            '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"' + str(index) + '","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
            for index in range(1, 4)
        ]) + ']}',
        '{"quiz_questions":[' + ','.join([
            '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"' + str((index - 1) % 4 + 1) + '","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
            for index in range(1, 11)
        ]) + ']}',
    ])
    def test_generate_quiz_retries_on_fewer_than_ten_questions(self, mock_generate_feature):
        user = User.objects.create_user(username='quizretry', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz Retry Paper', pdf_file=SimpleUploadedFile('quiz-retry.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        mock_provider = Mock()
        mock_provider.generate = Mock(return_value='{"quiz_questions":[' + ','.join([
            '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"' + str((index - 1) % 4 + 1) + '","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
            for index in range(1, 11)
        ]) + ']}')

        with patch('papers.quiz_service.ProviderFactory.create_provider', return_value=mock_provider):
            questions = generate_quiz(paper)

        self.assertEqual(len(questions), 10)
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(mock_provider.generate.call_count, 1)

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":"' + str((index - 1) % 4 + 1) + '","difficulty":"Easy","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 11)
    ]) + ']}')
    def test_generate_quiz_accepts_string_number_correct_answer(self, mock_generate_feature):
        user = User.objects.create_user(username='quizstrnum', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Quiz StrNum Paper', pdf_file=SimpleUploadedFile('quiz-strnum.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='This paper studies a method and reports results.', extraction_status='Ready')

        questions = generate_quiz(paper)

        self.assertEqual(len(questions), 10)
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 10)
        self.assertEqual(mock_generate_feature.call_count, 1)
        self.assertEqual(questions[0].correct_answer, 'Option A')
        self.assertEqual(questions[1].correct_answer, 'Option B')
        self.assertEqual(questions[2].correct_answer, 'Option C')
        self.assertEqual(questions[3].correct_answer, 'Option D')
        self.assertEqual(questions[4].correct_answer, 'Option A')
        self.assertEqual(questions[2].correct_answer, 'Option C')
        self.assertEqual(questions[3].correct_answer, 'Option D')
        self.assertEqual(questions[2].correct_answer, 'Option C')
        self.assertEqual(questions[3].correct_answer, 'Option D')

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.quiz_service.AIService.generate_feature', return_value='{"quiz_questions":[' + ','.join([
        '{"question":"Question ' + str(index) + '","options":["Option A","Option B","Option C","Option D"],"correct_answer":1,"difficulty":"' + ('Easy' if index <= 3 else 'Medium' if index <= 7 else 'Hard') + '","explanation":"Explanation ' + str(index) + '"}'
        for index in range(1, 11)
    ]) + ']}')
    def test_quiz_page_shows_generate_button_and_can_generate_quiz(self, mock_generate_feature):
        user = User.objects.create_user(username='quizview', password='Secret123')
        _create_premium_subscription(user)
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
        self.assertEqual(QuizQuestion.objects.filter(paper=paper).count(), 10)

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
        _create_premium_subscription(user)
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
        _create_premium_subscription(user)
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

        def fake_generate(prompt, max_completion_tokens=None):
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


def _tech_json(word_count):
    phrase = 'word '
    text = (phrase * word_count).strip()
    return '{"technical_explanation": "' + text + '"}'


def _tech_text(word_count):
    """Return just the word-count-controlled explanation text (no JSON wrapper)."""
    phrase = 'word '
    return (phrase * word_count).strip()


class TechnicalExplanationWordCountTests(TestCase):
    """Unit tests for the word-count validation in technical explanation generation."""

    def test_response_within_target_range_is_accepted(self):
        cleaned = _clean_technical_markdown(_tech_json(600))
        self.assertEqual(cleaned, _tech_text(600))

    def test_response_at_minimum_threshold_is_accepted(self):
        cleaned = _clean_technical_markdown(_tech_json(450))
        self.assertEqual(cleaned, _tech_text(450))

    def test_response_at_maximum_threshold_is_accepted(self):
        cleaned = _clean_technical_markdown(_tech_json(850))
        self.assertEqual(cleaned, _tech_text(850))

    def test_response_below_minimum_threshold_is_rejected(self):
        self.assertIsNone(_clean_technical_markdown(_tech_json(449)))

    def test_response_above_maximum_threshold_is_rejected(self):
        self.assertIsNone(_clean_technical_markdown(_tech_json(851)))

    def test_empty_response_is_rejected_with_error(self):
        with self.assertRaises(TechnicalExplanationError):
            _clean_technical_markdown('{"technical_explanation": ""}')

    def test_extremely_short_response_returns_none(self):
        # Non-empty but far-too-short text: word-count check returns None;
        # TechnicalExplanationError is raised by the caller, not this function.
        self.assertIsNone(_clean_technical_markdown('{"technical_explanation": "too short"}'))

    def test_excessively_long_response_is_rejected(self):
        long_text = _tech_json(900)
        self.assertIsNone(_clean_technical_markdown(long_text))

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate')
    def test_valid_slightly_under_target_response_is_stored(self, mock_generate):
        user = User.objects.create_user(username='techunder', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Under Target Paper', pdf_file=SimpleUploadedFile('under.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='A paper about neural network optimization techniques.', extraction_status='Ready')

        mock_generate.return_value = '{"technical_explanation":"' + _tech_text(470) + '","beginner_explanation":"Simple","key_contributions":[],"key_concepts":[],"reading_difficulty":{"level":"Intermediate","reason":""},"glossary":[],"flashcards":[],"viva_questions":[]}'

        self.client.force_login(user)
        response = self.client.post(reverse('paper_technical', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.analysis_status, 'Ready')
        self.assertEqual(analysis.technical_explanation, _tech_text(470))

    @override_settings(AI_PROVIDER='mock')
    @patch('papers.ai_providers.MockProvider.generate')
    def test_valid_slightly_over_target_response_is_stored(self, mock_generate):
        user = User.objects.create_user(username='techover', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Over Target Paper', pdf_file=SimpleUploadedFile('over.pdf', b'%PDF-1.4\n', content_type='application/pdf'))
        PaperContent.objects.create(paper=paper, extracted_text='A paper about distributed systems and consensus algorithms.', extraction_status='Ready')

        mock_generate.return_value = '{"technical_explanation":"' + _tech_text(760) + '","beginner_explanation":"Simple","key_contributions":[],"key_concepts":[],"reading_difficulty":{"level":"Intermediate","reason":""},"glossary":[],"flashcards":[],"viva_questions":[]}'

        self.client.force_login(user)
        response = self.client.post(reverse('paper_technical', args=[paper.pk]), follow=True)

        self.assertEqual(response.status_code, 200)
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.analysis_status, 'Ready')
        self.assertEqual(analysis.technical_explanation, _tech_text(760))


class LearningNavigationTests(TestCase):
    def test_beginner_page_has_next_button(self):
        user = User.objects.create_user(username='navbeginner', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Nav Paper', pdf_file='papers/nav.pdf')
        AIAnalysis.objects.create(paper=paper, beginner_explanation='Beginner content')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/papers/1/technical/"')
        self.assertContains(response, 'Next')

    def test_technical_page_has_next_button(self):
        user = User.objects.create_user(username='navtechnical', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Tech Paper', pdf_file='papers/navtech.pdf')
        AIAnalysis.objects.create(paper=paper, technical_explanation='Technical content')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/papers/1/sections/"')
        self.assertContains(response, 'Next')

    def test_notes_page_has_back_to_papers_button(self):
        user = User.objects.create_user(username='navnotes', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Notes Paper', pdf_file='papers/navnotes.pdf')
        AIAnalysis.objects.create(paper=paper, revision_notes='Notes content')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_notes', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Back to My Papers')

    def test_section_accordion_has_next_button(self):
        user = User.objects.create_user(username='navsections', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Sections Paper', pdf_file='papers/navsec.pdf')
        PaperSection.objects.create(paper=paper, title='Abstract', section_order=0, summary='Abstract summary')
        PaperSection.objects.create(paper=paper, title='Introduction', section_order=1, summary='Intro summary')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_sections', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Abstract')
        self.assertContains(response, 'Introduction')
        self.assertContains(response, 'Next')

    def test_quiz_last_question_shows_done_button(self):
        user = User.objects.create_user(username='quizdone', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Quiz Done Paper', pdf_file='papers/quizdone.pdf')
        QuizQuestion.objects.create(
            paper=paper,
            question='What is the answer?',
            option_a='A',
            option_b='B',
            option_c='C',
            option_d='D',
            correct_answer='A',
            display_order=0,
        )
        self.client.force_login(user)
        response = self.client.get(reverse('paper_quiz', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Done')

    def test_section_next_navigates_to_next_module(self):
        user = User.objects.create_user(username='navlast', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Last Paper', pdf_file='papers/navlast.pdf')
        PaperSection.objects.create(paper=paper, title='Conclusion', section_order=0, summary='Conclusion summary')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_sections', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/papers/1/glossary/"')

    def test_beginner_page_has_no_previous_button(self):
        user = User.objects.create_user(username='navbeginnerprev', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Nav Paper', pdf_file='papers/nav.pdf')
        AIAnalysis.objects.create(paper=paper, beginner_explanation='Beginner content')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Previous')

    def test_technical_page_has_previous_button(self):
        user = User.objects.create_user(username='navtechnicalprev', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Tech Paper', pdf_file='papers/navtech.pdf')
        AIAnalysis.objects.create(paper=paper, technical_explanation='Technical content')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Previous')
        self.assertContains(response, 'href="/papers/1/beginner/"')

    def test_section_page_has_previous_button(self):
        user = User.objects.create_user(username='navsectionprev', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Nav Section Prev', pdf_file='papers/navsecprev.pdf')
        PaperSection.objects.create(paper=paper, title='Abstract', section_order=0, summary='Abstract summary')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_sections', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Previous')
        self.assertContains(response, 'href="/papers/1/technical/"')


class PremiumBadgeColorTests(TestCase):
    def test_basic_user_sees_golden_premium_badges(self):
        user = User.objects.create_user(username='badgebasic', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Badge Paper', pdf_file='papers/badge.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bg-warning text-dark')

    def test_premium_user_sees_green_premium_badges(self):
        user = User.objects.create_user(username='badgepremium', password='Secret123')
        _create_premium_subscription(user)
        paper = Paper.objects.create(owner=user, title='Badge Premium Paper', pdf_file='papers/badgeprem.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bg-success text-white')

    def test_expired_user_sees_golden_premium_badges(self):
        user = User.objects.create_user(username='badgeexpired', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-badge-expired',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=timezone.now() - timedelta(days=10),
            end_date=timezone.now() - timedelta(days=3),
        )
        paper = Paper.objects.create(owner=user, title='Badge Expired Paper', pdf_file='papers/badgeexp.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bg-warning text-dark')


class ReviewSystemTests(TestCase):
    def test_authenticated_user_can_submit_review(self):
        user = User.objects.create_user(username='reviewer', password='Secret123')
        self.client.force_login(user)
        response = self.client.post(
            reverse('review_submit'),
            {'rating': 5, 'comment': 'Great platform!'},
        )
        self.assertRedirects(response, reverse('review_list'))
        review = Review.objects.get(user=user)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.comment, 'Great platform!')
        self.assertFalse(review.is_approved)

    def test_review_is_associated_with_authenticated_user(self):
        user = User.objects.create_user(username='reviewowner', password='Secret123')
        self.client.force_login(user)
        self.client.post(
            reverse('review_submit'),
            {'rating': 4, 'comment': 'Nice!'},
        )
        review = Review.objects.first()
        self.assertEqual(review.user, user)

    def test_invalid_rating_is_rejected(self):
        user = User.objects.create_user(username='badrating', password='Secret123')
        self.client.force_login(user)
        response = self.client.post(
            reverse('review_submit'),
            {'rating': 6, 'comment': 'Great!'},
        )
        self.assertRedirects(response, reverse('review_list'))
        self.assertEqual(Review.objects.count(), 0)

    def test_unapproved_reviews_not_publicly_displayed(self):
        user = User.objects.create_user(username='unapproved', password='Secret123')
        Review.objects.create(user=user, rating=5, comment='Secret', is_approved=False)
        response = self.client.get(reverse('review_list'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Secret')

    def test_approved_reviews_are_publicly_displayed(self):
        user = User.objects.create_user(username='approved', password='Secret123')
        review = Review.objects.create(user=user, rating=5, comment='Public', is_approved=True)
        response = self.client.get(reverse('review_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public')
        self.assertContains(response, user.username)

    def test_users_cannot_submit_review_for_another_user(self):
        owner = User.objects.create_user(username='owner', password='Secret123')
        other = User.objects.create_user(username='other', password='Secret123')
        self.client.force_login(other)
        self.client.post(
            reverse('review_submit'),
            {'rating': 5, 'comment': 'Fake review'},
        )
        reviews = Review.objects.filter(user=other)
        self.assertEqual(reviews.count(), 1)
        self.assertEqual(reviews.first().user, other)
