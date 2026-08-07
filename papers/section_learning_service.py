import logging
import re

from django.core.exceptions import ObjectDoesNotExist

from .ai_service import AIService
from .models import PaperContent, PaperSection
from .prompts.section_learning import build_section_learning_prompt
from .response_validator import validate_json_response
from .section_parser import parse_sections

logger = logging.getLogger(__name__)


class SectionLearningError(ValueError):
    """Application-level error raised when section learning generation fails."""


def _extract_section_title(item):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ('title', 'heading', 'name', 'section', 'label'):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in item.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


def _coerce_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_section_payload(raw_section, fallback_title, fallback_order):
    if not isinstance(raw_section, dict):
        raise SectionLearningError('AI returned an invalid section explanation payload.')

    title = _extract_section_title(raw_section) or fallback_title
    if title == fallback_title and title == 'Section':
        title = fallback_title

    summary = str(raw_section.get('summary') or '').strip()
    purpose = str(raw_section.get('purpose') or '').strip()
    conclusion = str(raw_section.get('conclusion') or '').strip()
    key_points = _coerce_list(raw_section.get('key_points'))
    important_terms = _coerce_list(raw_section.get('important_terms'))
    student_note = str(raw_section.get('student_note') or '').strip()

    if not summary and not purpose and not key_points and not important_terms and not student_note:
        if isinstance(raw_section.get('content'), str) and raw_section.get('content').strip():
            summary = raw_section.get('content').strip()
        elif len(raw_section) == 1 and isinstance(next(iter(raw_section.values())), str):
            summary = next(iter(raw_section.values())).strip()
        else:
            raise SectionLearningError('AI response did not include any usable section explanation content.')

    return {
        'title': title,
        'order': int(raw_section.get('order') or fallback_order),
        'summary': summary,
        'purpose': purpose,
        'conclusion': conclusion,
        'key_points': key_points,
        'important_terms': important_terms,
        'student_note': student_note,
    }


def _coerce_section_payload(item, fallback_title, fallback_order):
    if not isinstance(item, dict):
        return {'title': fallback_title, 'order': fallback_order}

    title = _extract_section_title(item) or fallback_title
    order_value = int(item.get('order') or fallback_order) if str(item.get('order') or fallback_order).isdigit() else fallback_order
    section_payload = {
        'title': title,
        'order': order_value,
        'summary': str(item.get('summary') or '').strip(),
        'purpose': str(item.get('purpose') or '').strip(),
        'conclusion': str(item.get('conclusion') or '').strip(),
        'key_points': _coerce_list(item.get('key_points')),
        'important_terms': _coerce_list(item.get('important_terms')),
        'student_note': str(item.get('student_note') or '').strip(),
    }
    return section_payload


def _clean_detection_payload(payload):
    if not isinstance(payload, dict):
        raise SectionLearningError('AI returned an invalid section detection payload.')

    sections = payload.get('sections')
    if sections is None:
        for key in ('section_titles', 'headings', 'titles', 'items'):
            if key in payload:
                sections = payload.get(key)
                break

    if isinstance(sections, dict):
        sections = list(sections.values())

    if not isinstance(sections, list) or not sections:
        raise SectionLearningError('AI response did not include any usable sections.')

    cleaned_sections = []
    for index, item in enumerate(sections, start=1):
        title = _extract_section_title(item)
        if not title:
            continue

        order = item.get('order') if isinstance(item, dict) else index
        order_value = int(order) if str(order).isdigit() else index
        cleaned_sections.append(_coerce_section_payload(item, title, order_value))

    if not cleaned_sections:
        raise SectionLearningError('AI response did not include any usable sections.')

    return sorted(cleaned_sections, key=lambda item: item['order'])


def _looks_like_heading(line):
    text = re.sub(r'\s+', ' ', line).strip()
    if not text:
        return False
    if len(text.split()) > 8:
        return False
    lowered = text.lower()
    heading_keywords = (
        'abstract', 'introduction', 'related work', 'background', 'methodology',
        'materials and methods', 'dataset', 'experiments', 'results', 'discussion',
        'limitations', 'conclusion', 'future work', 'appendix'
    )
    if lowered in heading_keywords or lowered.startswith(heading_keywords):
        return True
    return bool(re.match(r'^(#+\s*)?[A-Z][A-Za-z0-9 /&()\-]{1,80}$', text))


def _prepare_section_text(text):
    if not text:
        return ''

    cleaned = re.sub(r'\s+', ' ', text).strip()
    if len(cleaned) <= 2200:
        return cleaned

    truncated = cleaned[:2200]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return truncated + ' [truncated]'


def _build_detection_context(extracted_text):
    if not extracted_text:
        return ''

    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    if not lines:
        return ''

    detected_headings = []
    for line in lines:
        if _looks_like_heading(line):
            detected_headings.append(line)

    if detected_headings:
        return _prepare_section_text('\n'.join(detected_headings[:20]))

    return _prepare_section_text('\n'.join(lines[:12]))


def _extract_sections_from_headings(extracted_text):
    if not extracted_text:
        return []

    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    sections = []
    for index, line in enumerate(lines):
        if _looks_like_heading(line):
            sections.append({'title': line, 'order': len(sections) + 1})

    return sections


def _extract_section_excerpt(extracted_text, section_title):
    if not extracted_text or not section_title:
        return _prepare_section_text(extracted_text or '')

    cleaned_title = re.sub(r'\s+', ' ', section_title).strip().lower()
    lines = extracted_text.splitlines()

    start_index = None
    for index, line in enumerate(lines):
        if cleaned_title in re.sub(r'\s+', ' ', line).strip().lower():
            start_index = index
            break

    if start_index is None:
        return _prepare_section_text(extracted_text)

    excerpt_lines = []
    for index in range(start_index + 1, len(lines)):
        if _looks_like_heading(lines[index]) and index > start_index + 1:
            break
        excerpt_lines.append(lines[index])

    excerpt = '\n'.join(excerpt_lines).strip()
    return _prepare_section_text(excerpt or extracted_text)


def _persist_section_learning(paper, cleaned_sections):
    PaperSection.objects.filter(paper=paper).delete()

    for item in cleaned_sections:
        PaperSection.objects.create(
            paper=paper,
            title=item['title'],
            section_order=item['order'],
            original_text=item.get('original_text', ''),
            summary=item['summary'],
            purpose=item['purpose'],
            conclusion=item.get('conclusion', ''),
            key_points=item['key_points'],
            important_terms=item['important_terms'],
            student_note=item['student_note'],
            is_generated=bool(item.get('summary') or item.get('purpose') or item.get('key_points') or item.get('important_terms') or item.get('student_note')),
        )

    return list(PaperSection.objects.filter(paper=paper).order_by('section_order', 'id'))


def _find_section_text(parsed_sections, section_title):
    if not section_title:
        return ''

    normalized_title = re.sub(r'\s+', ' ', section_title).strip().lower()
    for parsed_section in parsed_sections:
        candidate_title = re.sub(r'\s+', ' ', parsed_section.get('title') or '').strip().lower()
        if candidate_title == normalized_title or candidate_title.startswith(normalized_title) or normalized_title.startswith(candidate_title):
            return parsed_section.get('text') or ''

    return ''


def generate_section_learning(paper, force_refresh=False):
    """Use a local parser first, then explain each detected section using compact section-level prompts."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise SectionLearningError('Paper content must exist before generating section learning.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise SectionLearningError('Paper content must contain extracted text before generating section learning.')

    existing_sections = list(PaperSection.objects.filter(paper=paper).order_by('section_order', 'id'))
    if existing_sections and not force_refresh:
        return existing_sections

    parsed_sections = parse_sections(content.extracted_text)
    if not parsed_sections:
        raise SectionLearningError('No sections could be detected from the paper text.')

    ai_service = AIService()
    detection_context = _build_detection_context(content.extracted_text)

    try:
        detection_response = ai_service.generate_feature('section_learning', detection_context, prompt_type='section_detection')
    except Exception as exc:
        error_text = str(exc).lower()
        if 'rate limit' in error_text or '429' in error_text or 'daily token limit' in error_text or 'tokens per day' in error_text:
            raise SectionLearningError('AI section generation is temporarily unavailable because the configured Groq account has reached its daily token limit (rate limit). Please try again later or use a different API key.') from exc
        raise SectionLearningError(f'AI section generation failed: {exc}') from exc

    valid, detection_payload, detection_error = validate_json_response(detection_response)
    detected_sections = []
    if valid and isinstance(detection_payload, dict):
        detected_sections = _clean_detection_payload(detection_payload)

    cleaned_sections = []
    if detected_sections:
        for index, detected_section in enumerate(detected_sections, start=1):
            section_title = detected_section['title']
            section_text = _find_section_text(parsed_sections, section_title) or content.extracted_text
            summary = str(detected_section.get('summary') or '').strip()
            purpose = str(detected_section.get('purpose') or '').strip()
            conclusion = str(detected_section.get('conclusion') or '').strip()
            key_points = _coerce_list(detected_section.get('key_points'))
            important_terms = _coerce_list(detected_section.get('important_terms'))
            student_note = str(detected_section.get('student_note') or '').strip()

            if not any([summary, purpose, key_points, important_terms, student_note]):
                try:
                    explanation_response = ai_service.generate_feature('section_learning', section_text, prompt_type='section_explanation', section_title=section_title)
                except Exception as exc:
                    error_text = str(exc).lower()
                    if 'rate limit' in error_text or '429' in error_text or 'daily token limit' in error_text or 'tokens per day' in error_text:
                        raise SectionLearningError('AI section generation is temporarily unavailable because the configured Groq account has reached its daily token limit (rate limit). Please try again later or use a different API key.') from exc
                    raise SectionLearningError(f'AI section generation failed: {exc}') from exc

                valid_explanation, explanation_payload, explanation_error = validate_json_response(explanation_response)
                if valid_explanation and isinstance(explanation_payload, dict):
                    summary = str(explanation_payload.get('summary') or '').strip()
                    purpose = str(explanation_payload.get('purpose') or '').strip()
                    conclusion = str(explanation_payload.get('conclusion') or '').strip()
                    key_points = _coerce_list(explanation_payload.get('key_points'))
                    important_terms = _coerce_list(explanation_payload.get('important_terms'))
                    student_note = str(explanation_payload.get('student_note') or '').strip()
                else:
                    summary = str(explanation_response or '').strip()

            cleaned_sections.append({
                'title': section_title,
                'order': index,
                'summary': summary,
                'purpose': purpose,
                'conclusion': conclusion,
                'key_points': key_points,
                'important_terms': important_terms,
                'student_note': student_note,
                'original_text': section_text,
            })
    else:
        for index, parsed_section in enumerate(parsed_sections, start=1):
            section_title = parsed_section['title']
            section_text = parsed_section['text']
            try:
                explanation_response = ai_service.generate_feature('section_learning', section_text, prompt_type='section_explanation', section_title=section_title)
            except Exception as exc:
                error_text = str(exc).lower()
                if 'rate limit' in error_text or '429' in error_text or 'daily token limit' in error_text or 'tokens per day' in error_text:
                    raise SectionLearningError('AI section generation is temporarily unavailable because the configured Groq account has reached its daily token limit (rate limit). Please try again later or use a different API key.') from exc
                raise SectionLearningError(f'AI section generation failed: {exc}') from exc

            valid_explanation, explanation_payload, explanation_error = validate_json_response(explanation_response)
            if valid_explanation and isinstance(explanation_payload, dict):
                summary = str(explanation_payload.get('summary') or '').strip()
                purpose = str(explanation_payload.get('purpose') or '').strip()
                conclusion = str(explanation_payload.get('conclusion') or '').strip()
                key_points = _coerce_list(explanation_payload.get('key_points'))
                important_terms = _coerce_list(explanation_payload.get('important_terms'))
                student_note = str(explanation_payload.get('student_note') or '').strip()
            else:
                summary = str(explanation_response or '').strip()
                purpose = ''
                conclusion = ''
                key_points = []
                important_terms = []
                student_note = ''

            cleaned_sections.append({
                'title': section_title,
                'order': index,
                'summary': summary,
                'purpose': purpose,
                'conclusion': conclusion,
                'key_points': key_points,
                'important_terms': important_terms,
                'student_note': student_note,
                'original_text': section_text,
            })

    return _persist_section_learning(paper, sorted(cleaned_sections, key=lambda item: item['order']))
