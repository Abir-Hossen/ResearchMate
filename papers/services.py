from io import BytesIO

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone

try:
    import fitz
except ImportError:  # pragma: no cover - environment fallback
    fitz = None

from .models import Paper, PaperContent
from .ai_services import MockLearningService
from .parser import MockPayloadParser


def get_user_paper(user, paper_id):
    return get_object_or_404(Paper, pk=paper_id, owner=user)


def get_paper_metadata(paper):
    return {
        'paper': paper,
        'title': paper.title,
        'uploaded_at': paper.uploaded_at,
        'status': paper.processing_status,
        'content_status': paper.content_status,
        'file_name': paper.pdf_file.name.split('/')[-1],
        'file_size': paper.pdf_file.size,
        'is_prepared': paper.content_status == 'Ready',
    }


def build_workspace_context(user, paper_id, active_tab):
    paper = get_user_paper(user, paper_id)

    try:
        analysis = paper.ai_analysis
    except ObjectDoesNotExist:
        analysis = None

    try:
        progress = paper.learning_progress
    except ObjectDoesNotExist:
        progress = None

    glossary_terms = []
    flashcards = []
    quiz_questions = []
    viva_questions = []
    analysis_contributions = []

    if analysis is not None:
        analysis_contributions = [item for item in analysis.key_contributions.splitlines() if item.strip()] if analysis.key_contributions else []

    try:
        glossary_terms = list(paper.glossary_terms.all().order_by('display_order', 'id'))
        flashcards = list(paper.flashcards.all().order_by('display_order', 'id'))
        quiz_questions = list(paper.quiz_questions.all().order_by('display_order', 'id'))
        viva_questions = list(paper.viva_questions.all().order_by('display_order', 'id'))
    except ObjectDoesNotExist:
        pass

    return {
        'paper': paper,
        'active_tab': active_tab,
        'analysis': analysis,
        'progress': progress,
        'glossary_terms': glossary_terms,
        'flashcards': flashcards,
        'quiz_questions': quiz_questions,
        'viva_questions': viva_questions,
        'analysis_contributions': analysis_contributions,
    }


def extract_pdf_content(paper):
    paper.processing_status = 'Processing'
    paper.save(update_fields=['processing_status'])

    content, created = PaperContent.objects.get_or_create(paper=paper)
    content.extraction_status = 'Processing'
    content.save(update_fields=['extraction_status'])

    try:
        with paper.pdf_file.open('rb') as pdf_handle:
            pdf_bytes = pdf_handle.read()
    except Exception:
        content.extraction_status = 'Failed'
        content.save(update_fields=['extraction_status'])
        paper.processing_status = 'Uploaded'
        paper.save(update_fields=['processing_status'])
        raise

    try:
        if fitz is not None:
            document = fitz.open(stream=pdf_bytes, filetype='pdf')
            extracted_text = '\n\n'.join(page.get_text() for page in document)
            page_count = document.page_count
            document.close()
        else:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(pdf_bytes))
            extracted_text = '\n\n'.join((page.extract_text() or '').strip() for page in reader.pages)
            page_count = len(reader.pages)

        content.extracted_text = extracted_text.strip()
        content.page_count = page_count
        content.extraction_status = 'Ready'
        content.extracted_at = timezone.now()
        content.save()
        paper.processing_status = 'Completed'
        paper.save(update_fields=['processing_status'])
        return content
    except Exception:
        content.extraction_status = 'Failed'
        content.save(update_fields=['extraction_status'])
        paper.processing_status = 'Uploaded'
        paper.save(update_fields=['processing_status'])
        raise


def process_mock_ai(paper):
    try:
        content = paper.content
    except ObjectDoesNotExist:
        content = None

    if content is None or not content.extracted_text:
        raise ValueError('Paper content must exist and contain extracted text before mock AI processing.')

    try:
        analysis = paper.ai_analysis
    except ObjectDoesNotExist:
        analysis = None

    if analysis is not None and analysis.analysis_status == 'Ready':
        return analysis

    service = MockLearningService(content.extracted_text)
    payload = service.build_payload()
    parser = MockPayloadParser(payload)
    return parser.create_models(paper)
