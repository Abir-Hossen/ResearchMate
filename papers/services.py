from io import BytesIO

from django.shortcuts import get_object_or_404
from django.utils import timezone

try:
    import fitz
except ImportError:  # pragma: no cover - environment fallback
    fitz = None

from .models import Paper, PaperContent


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
    return {
        'paper': paper,
        'active_tab': active_tab,
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
