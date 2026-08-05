from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.pdfgen import canvas

from .models import AIAnalysis, Flashcard, Glossary, LearningProgress, Paper, PaperContent, QuizQuestion, VivaQuestion
from .prompts.beginner import build_beginner_prompt
from .prompts.technical import build_technical_prompt
from .response_validator import validate_json_response
from .services import _get_user_facing_error_message


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
    def test_start_learning_generates_mock_learning_materials(self):
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
        self.assertTrue(Glossary.objects.filter(paper=paper).exists())
        self.assertTrue(Flashcard.objects.filter(paper=paper).exists())
        self.assertFalse(QuizQuestion.objects.filter(paper=paper).exists())
        self.assertTrue(VivaQuestion.objects.filter(paper=paper).exists())
        self.assertTrue(LearningProgress.objects.filter(paper=paper).exists())

    @override_settings(AI_PROVIDER='groq', GROQ_API_KEY='test-key', GROQ_MODEL='llama-3.3-70b-versatile')
    @patch('papers.ai_providers.GroqProvider.generate', return_value='{"beginner_explanation":"A simple explanation","technical_explanation":"A technical explanation","key_contributions":["Important contribution"],"key_concepts":["Core concept"],"reading_difficulty":{"level":"Intermediate","reason":"Needs background knowledge"},"section_learning":[{"section":"Introduction","summary":"Read the intro first"}],"glossary":[{"term":"Neuron","simple_explanation":"A nerve cell","technical_explanation":"Specialized cell transmitting signals","example":"Neurons communicate through synapses"}],"flashcards":[{"question":"What is a neuron?","answer":"A nerve cell"}],"viva_questions":[{"question":"What is the main contribution?","suggested_answer":"It advances the field","follow_up_question":"Why is it significant?"}]}')
    def test_start_learning_uses_groq_payload_to_create_learning_materials(self, mock_generate):
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
        self.assertTrue(AIAnalysis.objects.filter(paper=paper).exists())
        self.assertTrue(Glossary.objects.filter(paper=paper).exists())
        self.assertTrue(Flashcard.objects.filter(paper=paper).exists())
        self.assertTrue(VivaQuestion.objects.filter(paper=paper).exists())
        analysis = AIAnalysis.objects.get(paper=paper)
        self.assertEqual(analysis.analysis_status, 'Ready')
        self.assertEqual(analysis.ai_model, 'groq')

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
