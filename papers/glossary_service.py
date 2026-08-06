import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import Glossary, LearningProgress, PaperContent
from .provider_factory import ProviderFactory


class GlossaryGenerationError(ValueError):
    """Raised when glossary generation fails."""


def _extract_glossary_sections(markdown_text):
    if not markdown_text or not isinstance(markdown_text, str):
        return []

    normalized = markdown_text.strip()
    if not normalized:
        return []

    sections = []
    blocks = re.split(r'(?m)^\s*---\s*$', normalized)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith('# AI Glossary'):
            block = re.sub(r'^#\s*AI Glossary\s*\n?', '', block, flags=re.I)
        if not block:
            continue

        entries = re.split(r'(?m)^##\s+', block)
        for entry in entries:
            if not entry.strip():
                continue
            lines = [line.rstrip() for line in entry.strip().splitlines() if line.strip()]
            if not lines:
                continue
            term = lines[0].strip()
            if term.lower().startswith('term name'):
                continue
            if '(' in term and term.endswith(')'):
                term = term.split('(', 1)[0].strip()
            explanation = ''
            role = ''

            explanation_match = re.search(r'(?im)^###\s*(?:Explanation|Definitions?)\s*$\n?(.*?)(?=^###\s+|^##\s+|\Z)', entry, flags=re.S)
            if explanation_match:
                explanation = re.sub(r'\s+', ' ', explanation_match.group(1)).strip()
            else:
                explanation_match = re.search(r'(?im)^(?:Explanation|Definitions?)\s*:\s*(.+)$', entry)
                if explanation_match:
                    explanation = re.sub(r'\s+', ' ', explanation_match.group(1)).strip()

            role_match = re.search(r'(?im)^###\s*(?:Role in This Paper|Role)\s*$\n?(.*)$', entry, flags=re.S)
            if role_match:
                role = re.sub(r'\s+', ' ', role_match.group(1)).strip()
            else:
                role_match = re.search(r'(?im)^(?:Role in This Paper|Role)\s*:\s*(.+)$', entry)
                if role_match:
                    role = re.sub(r'\s+', ' ', role_match.group(1)).strip()

            if term and (explanation or role):
                sections.append({'term': term, 'explanation': explanation, 'paper_role': role})

    return sections


def _clean_glossary_entries(raw_entries):
    cleaned = []
    seen_terms = set()
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue
        term = str(entry.get('term') or '').strip()
        if not term or term.lower() in seen_terms:
            continue
        seen_terms.add(term.lower())
        cleaned.append({
            'term': term,
            'explanation': str(entry.get('explanation') or entry.get('simple_explanation') or '').strip(),
            'paper_role': str(entry.get('paper_role') or entry.get('role') or entry.get('role_in_this_paper') or '').strip(),
            'simple_explanation': str(entry.get('simple_explanation') or '').strip(),
            'technical_explanation': str(entry.get('technical_explanation') or '').strip(),
            'example': str(entry.get('example') or '').strip(),
            'display_order': index,
        })
    return cleaned


def generate_glossary(paper):
    """Generate a paper-specific glossary from stored extracted text and persist it."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise GlossaryGenerationError('Paper content must exist before generating a glossary.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise GlossaryGenerationError('Paper content must contain extracted text before generating a glossary.')

    provider = None
    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        raw_response = ai_service.generate_feature('glossary', content.extracted_text)
    except Exception as exc:
        raise GlossaryGenerationError('Glossary generation failed. Please try again later.') from exc

    if not raw_response or not str(raw_response).strip():
        raise GlossaryGenerationError('The AI provider returned an empty glossary response.')

    parsed_entries = _extract_glossary_sections(str(raw_response))
    if not parsed_entries:
        raise GlossaryGenerationError('The AI provider returned an invalid glossary response.')

    cleaned_entries = _clean_glossary_entries(parsed_entries)
    if not cleaned_entries:
        raise GlossaryGenerationError('The AI provider returned an invalid glossary response.')

    Glossary.objects.filter(paper=paper).delete()
    created_entries = []
    for entry in cleaned_entries:
        created_entries.append(Glossary.objects.create(
            paper=paper,
            term=entry['term'],
            explanation=entry['explanation'],
            paper_role=entry['paper_role'],
            simple_explanation=entry['simple_explanation'],
            technical_explanation=entry['technical_explanation'],
            example=entry['example'],
            display_order=entry['display_order'],
        ))

    progress, _ = LearningProgress.objects.get_or_create(paper=paper)
    progress.glossary_completed = True
    progress.last_accessed = timezone.now()
    progress.save(update_fields=['glossary_completed', 'last_accessed'])

    return created_entries
