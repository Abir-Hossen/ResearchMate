import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import AIAnalysis, PaperContent
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response


class RevisionNotesGenerationError(ValueError):
    """Raised when revision notes generation fails."""


def _clean_revision_notes(raw_response):
    if not raw_response or not str(raw_response).strip():
        raise RevisionNotesGenerationError('The AI provider returned an empty revision notes response.')

    candidate = str(raw_response).strip()
    if candidate.startswith('```'):
        candidate = re.sub(r'^```(?:markdown)?\s*|\s*```$', '', candidate, flags=re.IGNORECASE | re.MULTILINE)

    cleaned = candidate.strip()
    if not cleaned:
        raise RevisionNotesGenerationError('The AI provider returned an empty revision notes response.')

    return cleaned


def generate_revision_notes(paper):
    """Generate concise revision notes from stored paper content and persist them."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise RevisionNotesGenerationError('Paper content must exist before generating revision notes.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise RevisionNotesGenerationError('Paper content must contain extracted text before generating revision notes.')

    analysis, _ = AIAnalysis.objects.get_or_create(paper=paper)
    if analysis.revision_notes and analysis.revision_notes.strip():
        return analysis.revision_notes

    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        prompt = ai_service.build_prompt('revision_notes', content.extracted_text)
        raw_response = ai_service.provider.generate(prompt)
    except Exception as exc:
        raise RevisionNotesGenerationError('Revision notes generation failed. Please try again later.') from exc

    notes = _clean_revision_notes(raw_response)
    analysis.revision_notes = notes
    analysis.analysis_status = 'Ready'
    analysis.analysis_error = ''
    analysis.ai_model = getattr(provider, 'model_name', None) or analysis.ai_model or 'groq'
    analysis.generated_at = analysis.generated_at or timezone.now()
    analysis.last_updated = timezone.now()
    analysis.save(update_fields=['revision_notes', 'analysis_status', 'analysis_error', 'ai_model', 'generated_at', 'last_updated'])

    return notes
