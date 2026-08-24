import json
import logging
import re

from django.core.exceptions import ObjectDoesNotExist

from .ai_service import AIService
from .models import PaperContent, PaperSection
from .prompts.section_learning import build_section_learning_prompt
from .response_validator import validate_json_response

logger = logging.getLogger(__name__)


def _repair_section_json(text):
    if not isinstance(text, str):
        return text

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
    if text.endswith("```"):
        text = re.sub(r'\n?```$', '', text)

    text = "".join(char for char in text if char >= " " or char in "\n\r\t")

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    text = text.replace("\n", "\n").replace("\r", "\r").replace("\t", "\t")
    text = re.sub(r'"\s*\n\s*"', " ", text)
    text = re.sub(r'"\s*\r\s*"', " ", text)
    text = re.sub(r'"\s*\t\s*"', " ", text)

    return text


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
    normalized = _strip_heading_prefixes(text)
    if not normalized:
        return False
    heading_keywords = (
        'abstract', 'introduction', 'related work', 'background', 'literature review',
        'methodology', 'methods', 'materials and methods', 'system architecture',
        'proposed method', 'implementation', 'dataset', 'experimental setup',
        'experiments', 'results', 'discussion', 'limitations', 'conclusion',
        'future work', 'appendix', 'references', 'bibliography', 'acknowledgements'
    )
    for keyword in heading_keywords:
        if normalized == keyword or normalized.startswith(keyword + ' ') or normalized.startswith(keyword + ':'):
            return True
    return False


def _strip_heading_prefixes(text):
    normalized = re.sub(r'\s+', ' ', text).strip().lower()
    # Strip chapter/section/part prefixes like "Chapter 1:", "Section 2", "Part A:"
    normalized = re.sub(r'^(?:chapter|section|part)\s+\w+\s*[.:\-]?\s*', '', normalized)
    # Strip letter prefixes like "a.", "a. b.", "i.", "ii."
    normalized = re.sub(r'^(?:[a-z]+\.\s+)*', '', normalized)
    # Strip numbered prefixes like "1.", "1.1", "1.1.1"
    normalized = re.sub(r'^\d+(?:\.\d+)*\.?\s*', '', normalized)
    # Strip hyphenated numbers like "1-"
    normalized = re.sub(r'^\d+\-\s*', '', normalized)
    # Strip parenthesized numbers like "(1)" or "1)" or "(1." or "1)."
    normalized = re.sub(r'^\(?\d+\)?\.?\s*', '', normalized)
    normalized = re.sub(r'^\)\.?\s*', '', normalized)
    # Strip letter-paren prefixes like "A)" or "a)"
    normalized = re.sub(r'^[a-z]\)\.?\s*', '', normalized)
    normalized = normalized.strip().rstrip('.:-')
    return normalized.strip()


def _section_matches_heading(section_title, heading_pattern):
    if not section_title or not heading_pattern:
        return False
    normalized = _strip_heading_prefixes(section_title)
    if not normalized:
        return False
    for keyword in heading_pattern.split('|'):
        keyword = keyword.strip()
        if not keyword:
            continue
        if normalized == keyword or normalized.startswith(keyword + ' ') or normalized.startswith(keyword + ':'):
            return True
    return False


def _prepare_section_text(text, max_chars=2200):
    if not text:
        return ''

    cleaned = re.sub(r'\s+', ' ', text).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    truncated = cleaned[:max_chars]
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


FIXED_SECTIONS = [
    ('Abstract', 'abstract'),
    ('Introduction', 'introduction'),
    ('Related Work', 'related work|literature review'),
    ('Methodology', 'methodology|methods|materials and methods|proposed method|system architecture|implementation'),
    ('Results and Discussion', 'results|discussion'),
    ('Conclusion', 'conclusion|conclusions|future work'),
]

COMBINED_SECTION_PATTERNS = {
    'Results and Discussion': ['results', 'discussion'],
}


SECTION_ALIASES = {
    'abstract': 'Abstract',
    'introduction': 'Introduction',
    'intro': 'Introduction',
    'related work': 'Related Work',
    'literature review': 'Related Work',
    'review': 'Related Work',
    'methodology': 'Methodology',
    'methods': 'Methodology',
    'method': 'Methodology',
    'materials and methods': 'Methodology',
    'proposed method': 'Methodology',
    'system architecture': 'Methodology',
    'implementation': 'Methodology',
    'results': 'Results and Discussion',
    'result': 'Results and Discussion',
    'discussion': 'Results and Discussion',
    'results and discussion': 'Results and Discussion',
    'result and discussion': 'Results and Discussion',
    'experimental results': 'Results and Discussion',
    'evaluation': 'Results and Discussion',
    'performance evaluation': 'Results and Discussion',
    'experiments': 'Results and Discussion',
    'conclusion': 'Conclusion',
    'conclusions': 'Conclusion',
    'conclusion and future work': 'Conclusion',
    'summary and conclusion': 'Conclusion',
    'future work': 'Conclusion',
}


def _normalize_section_title(title):
    normalized = _strip_heading_prefixes(title)
    return SECTION_ALIASES.get(normalized, title.strip())


def _section_matches_heading(section_title, heading_pattern):
    if not section_title or not heading_pattern:
        return False
    normalized = _strip_heading_prefixes(section_title)
    if not normalized:
        return False
    for keyword in heading_pattern.split('|'):
        keyword = keyword.strip()
        if not keyword:
            continue
        if normalized == keyword or normalized.startswith(keyword + ' ') or normalized.startswith(keyword + ':'):
            return True
    return False


def _extract_combined_section_text(extracted_text, heading_patterns):
    if not extracted_text or not heading_patterns:
        return ''

    lines = extracted_text.splitlines()
    excerpts = []

    for pattern in heading_patterns:
        pattern = pattern.strip()
        if not pattern:
            continue

        start_index = None
        matched_line_index = None

        for index, line in enumerate(lines):
            normalized_line = re.sub(r'\s+', ' ', line).strip().lower()
            if not normalized_line:
                continue
            if _section_matches_heading(normalized_line, pattern):
                start_index = index + 1
                matched_line_index = index
                break

        if start_index is None or start_index >= len(lines):
            continue

        excerpt_lines = []
        for index in range(start_index, len(lines)):
            normalized_line = re.sub(r'\s+', ' ', lines[index]).strip().lower()
            if not normalized_line:
                continue
            if _section_matches_heading(normalized_line, pattern) and index > matched_line_index + 1:
                break
            if _looks_like_heading(lines[index]) and index > matched_line_index + 1:
                break
            excerpt_lines.append(lines[index])

        excerpt = '\n'.join(excerpt_lines).strip()
        if excerpt:
            excerpts.append(excerpt)

    if not excerpts:
        return ''

    combined = '\n\n'.join(excerpts)
    return _prepare_section_text(combined)


def _extract_section_excerpt(extracted_text, section_title, heading_pattern=None):
    if not extracted_text:
        return ''

    lines = extracted_text.splitlines()
    start_index = None
    matched_line_index = None

    for index, line in enumerate(lines):
        normalized_line = re.sub(r'\s+', ' ', line).strip().lower()
        if not normalized_line:
            continue

        if heading_pattern and _section_matches_heading(normalized_line, heading_pattern):
            start_index = index + 1
            matched_line_index = index
            break

        if not heading_pattern and section_title:
            cleaned_title = re.sub(r'\s+', ' ', section_title).strip().lower()
            if cleaned_title in normalized_line:
                start_index = index + 1
                matched_line_index = index
                break

    if start_index is None or start_index >= len(lines):
        return ''

    excerpt_lines = []
    for index in range(start_index, len(lines)):
        normalized_line = re.sub(r'\s+', ' ', lines[index]).strip().lower()
        if not normalized_line:
            continue
        if index > matched_line_index + 1 and _looks_like_heading(lines[index]):
            break
        excerpt_lines.append(lines[index])

    excerpt = '\n'.join(excerpt_lines).strip()
    return _prepare_section_text(excerpt or '')


def _extract_paper_context(extracted_text, max_chars=600):
    """Extract a brief paper context for grounding section explanations."""
    if not extracted_text:
        return ''

    text = re.sub(r'\s+', ' ', extracted_text).strip()
    
    abstract_match = re.search(r'abstract[:\s]+(.*?)(?:\n\n|\Z)', text, re.IGNORECASE | re.DOTALL)
    if abstract_match:
        abstract_text = abstract_match.group(1).strip()
        if len(abstract_text) > max_chars:
            abstract_text = abstract_text[:max_chars].rsplit(' ', 1)[0] + '...'
        return abstract_text

    intro_match = re.search(r'introduction[:\s]+(.*?)(?:\n\n|\Z)', text, re.IGNORECASE | re.DOTALL)
    if intro_match:
        intro_text = intro_match.group(1).strip()
        if len(intro_text) > max_chars:
            intro_text = intro_text[:max_chars].rsplit(' ', 1)[0] + '...'
        return intro_text

    if len(text) > max_chars:
        return text[:max_chars].rsplit(' ', 1)[0] + '...'
    return text


def _persist_section_learning(paper, cleaned_sections):
    PaperSection.objects.filter(paper=paper).delete()

    for item in cleaned_sections:
        PaperSection.objects.create(
            paper=paper,
            title=item['title'],
            section_order=item['order'],
            original_text=item.get('original_text', ''),
            summary=item['summary'],
            purpose=item.get('purpose', ''),
            conclusion=item.get('conclusion', ''),
            key_points=item.get('key_points', []),
            important_terms=item.get('important_terms', []),
            student_note=item.get('student_note', ''),
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


def _build_section_overview(extracted_text):
    if not extracted_text:
        return ''

    lines = extracted_text.splitlines()
    sections = []
    current_heading = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if _looks_like_heading(stripped):
            if current_heading and current_lines:
                sections.append((current_heading, '\n'.join(current_lines).strip()))
            current_heading = stripped
            current_lines = []
        elif current_heading is not None:
            current_lines.append(stripped)

    if current_heading and current_lines:
        sections.append((current_heading, '\n'.join(current_lines).strip()))

    overview_parts = []
    for heading, content in sections:
        words = content.split()[:80]
        snippet = ' '.join(words)
        if len(content.split()) > 80:
            snippet += '...'
        overview_parts.append(f'{heading}:\n{snippet}')

    overview = '\n\n'.join(overview_parts)
    return _prepare_section_text(overview)


def _build_section_explanation_context(extracted_text):
    """Build a context string with actual extracted text for each canonical section.

    This replaces the old 80-word snippet overview with section-specific source
    text so the AI can generate grounded explanations instead of guessing.
    """
    if not extracted_text:
        return '', {}

    full_text_prepared = _prepare_section_text(extracted_text, max_chars=2200)
    parts = []
    section_texts = {}
    for fixed_title, heading_pattern in FIXED_SECTIONS:
        combined_patterns = COMBINED_SECTION_PATTERNS.get(fixed_title)
        if combined_patterns:
            excerpt = _extract_combined_section_text(extracted_text, combined_patterns)
        else:
            excerpt = _extract_section_excerpt(extracted_text, fixed_title, heading_pattern=heading_pattern)

        if not excerpt or excerpt == full_text_prepared:
            excerpt = ''

        if excerpt:
            excerpt = _prepare_section_text(excerpt, max_chars=800)
        if excerpt:
            section_texts[fixed_title] = excerpt
            parts.append(f'{fixed_title}:\n{excerpt}')
        else:
            section_texts[fixed_title] = ''
            parts.append(f'{fixed_title}:\n[No text available for this section]')

    context = '\n\n'.join(parts)
    return context, section_texts


def generate_section_learning(paper, force_refresh=False):
    """
    Generate section learning explanations using per-section extracted text.

    For each canonical section, extracts the actual section text from the paper
    and sends it to the AI in a single request so explanations are grounded in
    the corresponding section content.
    """
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise SectionLearningError('Paper content must exist before generating section learning.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise SectionLearningError('Paper content must contain extracted text before generating section learning.')

    existing_sections = list(PaperSection.objects.filter(paper=paper).order_by('section_order', 'id'))
    if existing_sections and not force_refresh:
        return existing_sections

    ai_service = AIService()
    last_error = None
    for attempt in range(2):
        try:
            section_context, section_texts = _build_section_explanation_context(content.extracted_text)
            prompt = build_section_learning_prompt(section_context)
            explanation_response = ai_service.generate_feature(
                'section_learning',
                section_context,
                prompt_type='section_detection',
            )
        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()
            if 'rate limit' in error_text or '429' in error_text or 'daily token limit' in error_text or 'tokens per day' in error_text:
                raise SectionLearningError('AI section generation is temporarily unavailable because the configured Groq account has reached its daily token limit (rate limit). Please try again later or use a different API key.') from exc
            continue

        if not explanation_response or not str(explanation_response).strip():
            last_error = SectionLearningError('Empty section learning response')
            continue

        valid_response, response_payload, response_error = validate_json_response(explanation_response)
        if not valid_response:
            repaired = _repair_section_json(explanation_response)
            valid_response, response_payload, response_error = validate_json_response(repaired)

        if valid_response and isinstance(response_payload, dict):
            raw_sections = response_payload.get('sections')
            if raw_sections:
                section_map = {}
                for raw_section in raw_sections:
                    if not isinstance(raw_section, dict):
                        continue
                    title = _extract_section_title(raw_section)
                    if not title:
                        continue
                    explanation = str(raw_section.get('explanation') or '').strip()
                    if not explanation:
                        for key in ('summary', 'description', 'content', 'text', 'student_note', 'purpose'):
                            if raw_section.get(key):
                                explanation = str(raw_section[key]).strip()
                                break
                    if not explanation:
                        continue
                    word_count = len(explanation.split())
                    if word_count > 150:
                        words = explanation.split()
                        explanation = ' '.join(words[:150])
                    normalized_title = _normalize_section_title(title)
                    if normalized_title not in section_map:
                        section_map[normalized_title] = explanation

                cleaned_sections = []
                for fixed_title, heading_pattern in FIXED_SECTIONS:
                    explanation = ''
                    for title_key, expl in section_map.items():
                        if _section_matches_heading(title_key, heading_pattern):
                            explanation = expl
                            break

                    if not explanation:
                        excerpt = section_texts.get(fixed_title, '')
                        if excerpt:
                            explanation = excerpt
                        else:
                            explanation = 'This section is not present in the paper.'

                    cleaned_sections.append({
                        'title': fixed_title,
                        'order': len(cleaned_sections) + 1,
                        'summary': explanation,
                        'purpose': '',
                        'conclusion': '',
                        'key_points': [],
                        'important_terms': [],
                        'student_note': '',
                        'original_text': '',
                    })

                return _persist_section_learning(paper, cleaned_sections)

        last_error = SectionLearningError(f'AI returned an invalid response: {response_error}')

    raise SectionLearningError('AI section generation failed. Please try again later.') from last_error
