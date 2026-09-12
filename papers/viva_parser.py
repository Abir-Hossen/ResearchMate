"""Viva-specific AI response parsing, normalization, and validation.

This module is used ONLY by the Viva Preparation pipeline (``papers.viva_service``).

It deliberately does not use or modify the shared ``papers.response_validator``
helper that every other AI feature relies on, so the viva pipeline can be made
resilient without changing global AI behaviour.

Supported input formats (tried in this order):

1. Valid JSON (backward compatible with the historical viva payload).
2. Deterministic structured text made of repeated ``QUESTION:`` / ``ANSWER:``
   blocks (the format the current viva prompt asks for).
3. Salvage of individually complete JSON objects inside an otherwise broken or
   truncated JSON response.

Every path returns the same normalized structure that the existing
``VivaQuestion`` model, view, and template already expect::

    [
        {
            'question': str,
            'suggested_answer': str,
            'follow_up_question': str,
            'difficulty': str,
            'category': str,
            'examiner_tip': str,
            'display_order': int,
        },
        ...
    ]
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Minimum number of valid question/answer pairs required for a usable viva set.
VIVA_MINIMUM_QUESTIONS = 3
# Maximum number of question/answer pairs persisted for a single paper.
VIVA_MAXIMUM_QUESTIONS = 15

DEFAULT_CATEGORY = 'Basic Understanding'
DEFAULT_DIFFICULTY = 'Medium'

# Model field limits (papers.models.VivaQuestion).
CATEGORY_MAX_LENGTH = 40
DIFFICULTY_MAX_LENGTH = 20

_MINIMUM_TEXT_LENGTH = 3

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_FENCE_LINE_RE = re.compile(r'^`{3,}[a-zA-Z0-9_+\-]*$')
_PLACEHOLDER_RE = re.compile(r'^<.*>$')
# Decorative separator lines such as "---", "***", "===" carry no viva content.
_SEPARATOR_LINE_RE = re.compile(r'^[-=_*~#\u2014\u2013\s]{3,}$')

# One label line of a viva block, e.g. "QUESTION: ...", "**Answer:** ...",
# "- ANSWER:", "QUESTION 3: ...". A colon separator is always required so that
# ordinary prose lines are never mistaken for labels.
_LABEL_RE = re.compile(
    r'^[ \t]*(?:[-*+\u2022>][ \t]*)*'          # optional bullet / quote markers
    r'(?:\d+[.)][ \t]*)?'                       # optional "1." or "1)" numbering
    r'(?:#{1,6}[ \t]*)?'                        # optional markdown heading marker
    r'(?:\*{1,3}|_{1,3})?[ \t]*'                # optional markdown emphasis
    r'(?P<label>question|q|answer|a|suggested[ _-]?answer|category|type|'
    r'difficulty|level|examiner[ _-]?tip|tip|hint)'
    r'[ \t]*(?:\d+)?[ \t]*'                     # optional index, e.g. "QUESTION 2:"
    r'(?:\*{1,3}|_{1,3})?[ \t]*'
    r':[ \t]*'
    r'(?P<value>.*)$',
    re.IGNORECASE,
)

_LABEL_FIELDS = {
    'question': 'question',
    'q': 'question',
    'answer': 'answer',
    'a': 'answer',
    'suggestedanswer': 'answer',
    'category': 'category',
    'type': 'category',
    'difficulty': 'difficulty',
    'level': 'difficulty',
    'examinertip': 'tip',
    'tip': 'tip',
    'hint': 'tip',
}

_CATEGORY_ALIASES = (
    ('critical', 'Critical Thinking'),
    ('technical', 'Technical Understanding'),
    ('methodolog', 'Technical Understanding'),
    ('basic', 'Basic Understanding'),
    ('general', 'Basic Understanding'),
    ('understanding', 'Basic Understanding'),
)

_DIFFICULTY_ALIASES = (
    ('easy', 'Easy'),
    ('basic', 'Easy'),
    ('beginner', 'Easy'),
    ('medium', 'Medium'),
    ('moderate', 'Medium'),
    ('intermediate', 'Medium'),
    ('hard', 'Hard'),
    ('difficult', 'Hard'),
    ('advanced', 'Hard'),
)


def normalize_whitespace(value):
    """Collapse all whitespace runs into single spaces and trim the result."""
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _stringify(value):
    """Convert a JSON value into readable plain text."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ' '.join(_stringify(item) for item in value if item is not None)
    if isinstance(value, dict):
        return ' '.join(_stringify(item) for item in value.values() if item is not None)
    return str(value)


def _first_non_empty(entry, keys):
    for key in keys:
        if key in entry:
            text = normalize_whitespace(_stringify(entry.get(key)))
            if text:
                return text
    return ''


def strip_code_fences(raw_text):
    """Normalize line endings and remove accidental markdown code fences."""
    candidate = '' if raw_text is None else str(raw_text)
    candidate = candidate.replace('\r\n', '\n').replace('\r', '\n').strip()
    candidate = _CONTROL_CHARS_RE.sub('', candidate)

    if '```' not in candidate:
        return candidate.strip()

    candidate = re.sub(r'^`{3,}[a-zA-Z0-9_+\-]*[ \t]*\n?', '', candidate)
    candidate = re.sub(r'\n?[ \t]*`{3,}[ \t]*$', '', candidate)
    kept_lines = [line for line in candidate.split('\n') if not _FENCE_LINE_RE.match(line.strip())]
    return '\n'.join(kept_lines).strip()


def _normalize_category(value):
    text = normalize_whitespace(value)
    if not text:
        return DEFAULT_CATEGORY

    lowered = text.lower()
    for marker, canonical in _CATEGORY_ALIASES:
        if marker in lowered:
            return canonical
    return text[:CATEGORY_MAX_LENGTH]


def _normalize_difficulty(value):
    lowered = normalize_whitespace(value).lower()
    if not lowered:
        return DEFAULT_DIFFICULTY

    for marker, canonical in _DIFFICULTY_ALIASES:
        if marker in lowered:
            return canonical
    return normalize_whitespace(value).title()[:DIFFICULTY_MAX_LENGTH]


def _is_usable_text(value):
    if not value or len(value) < _MINIMUM_TEXT_LENGTH:
        return False
    return not _PLACEHOLDER_RE.match(value)


def _build_entry(question, answer, category=None, difficulty=None, tip=None):
    """Validate one raw viva item and return the normalized dict, or None."""
    question_text = normalize_whitespace(question)
    answer_text = normalize_whitespace(answer)

    if not _is_usable_text(question_text) or not _is_usable_text(answer_text):
        return None

    return {
        'question': question_text,
        'suggested_answer': answer_text,
        'follow_up_question': '',
        'difficulty': _normalize_difficulty(difficulty),
        'category': _normalize_category(category),
        'examiner_tip': normalize_whitespace(tip),
        'display_order': 0,
    }


def _finalize(entries):
    """Drop duplicate questions and assign a stable display order."""
    finalized = []
    seen_questions = set()

    for entry in entries:
        if not entry:
            continue
        key = entry['question'].lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        entry = dict(entry)
        entry['display_order'] = len(finalized) + 1
        finalized.append(entry)

    return finalized


def normalize_viva_entries(raw_entries):
    """Normalize already-structured viva entries (dict or QA pair sequences)."""
    normalized = []
    for raw_entry in raw_entries or []:
        if isinstance(raw_entry, dict):
            entry = _build_entry(
                question=_first_non_empty(raw_entry, ('question', 'Question', 'viva_question', 'prompt')),
                answer=_first_non_empty(raw_entry, (
                    'answer',
                    'Answer',
                    'suggested_answer',
                    'suggestedAnswer',
                    'model_answer',
                    'expected_answer',
                    'response',
                )),
                category=_first_non_empty(raw_entry, ('category', 'Category', 'group', 'section')),
                difficulty=_first_non_empty(raw_entry, ('difficulty', 'Difficulty', 'level')),
                tip=_first_non_empty(raw_entry, (
                    'examiner_tip',
                    'examinerTip',
                    'tip',
                    'hint',
                    'follow_up_question',
                )),
            )
        elif isinstance(raw_entry, (list, tuple)) and len(raw_entry) >= 2:
            entry = _build_entry(question=raw_entry[0], answer=raw_entry[1])
        else:
            entry = None

        if entry is not None:
            normalized.append(entry)

    return _finalize(normalized)


def _json_candidates(text):
    candidates = [text]

    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    start, end = text.find('['), text.rfind(']')
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])

    return candidates


def _entries_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('viva_questions', 'vivaQuestions', 'viva', 'questions', 'items', 'data'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if payload.get('question'):
            return [payload]
    return []


def parse_viva_json(raw_text):
    """Parse the historical valid-JSON viva format. Returns [] when not JSON."""
    for candidate in _json_candidates(raw_text):
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue

        entries = normalize_viva_entries(_entries_from_payload(payload))
        if entries:
            return entries

    return []


def parse_viva_structured_text(raw_text):
    """Parse repeated ``QUESTION:`` / ``ANSWER:`` blocks from plain text."""
    blocks = []
    current = None
    active_field = None

    for raw_line in raw_text.split('\n'):
        line = raw_line.strip()
        if not line or _SEPARATOR_LINE_RE.match(line):
            # Blank lines and decorative separators are harmless; they never
            # break a block and are never treated as content.
            continue

        match = _LABEL_RE.match(line)
        if match:
            field = _LABEL_FIELDS.get(re.sub(r'[ _-]', '', match.group('label')).lower())
            value = match.group('value').strip().strip('*_').strip()

            if field == 'question':
                if current is not None:
                    blocks.append(current)
                current = {'question': [], 'answer': [], 'category': [], 'difficulty': [], 'tip': []}

            if current is None or field is None:
                # Commentary or labels before the first QUESTION are ignored.
                continue

            active_field = field
            if value:
                current[field].append(value)
            continue

        if current is None or active_field is None:
            continue

        # Continuation line for the label that is currently open.
        current[active_field].append(line)

    if current is not None:
        blocks.append(current)

    normalized = []
    for block in blocks:
        entry = _build_entry(
            question=' '.join(block['question']),
            answer=' '.join(block['answer']),
            category=' '.join(block['category']),
            difficulty=' '.join(block['difficulty']),
            tip=' '.join(block['tip']),
        )
        if entry is not None:
            normalized.append(entry)

    return _finalize(normalized)


def salvage_viva_json_objects(raw_text):
    """Recover individually complete JSON objects from broken/truncated JSON.

    A response that was cut off at the provider token limit still contains many
    complete ``{...}`` objects. Those are recovered instead of discarding the
    whole response.
    """
    recovered = []
    open_positions = []
    in_string = False
    escaped = False

    for index, char in enumerate(raw_text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == '{':
            open_positions.append(index)
        elif char == '}' and open_positions:
            start = open_positions.pop()
            try:
                parsed = json.loads(raw_text[start:index + 1])
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict) and (parsed.get('question') or parsed.get('Question')):
                recovered.append(parsed)

    return normalize_viva_entries(recovered)


def parse_viva_response(raw_response):
    """Convert any raw viva AI response into normalized, validated viva entries.

    Never raises for malformed content: unusable items are skipped and the valid
    remainder is returned. An empty list means nothing usable was found.
    """
    if isinstance(raw_response, (dict, list)):
        entries = normalize_viva_entries(_entries_from_payload(raw_response))
        if entries:
            return entries
        return []

    text = strip_code_fences(raw_response)
    if not text:
        return []

    for parser in (parse_viva_json, parse_viva_structured_text, salvage_viva_json_objects):
        entries = parser(text)
        if entries:
            logger.debug('Viva response parsed by %s with %s valid items.', parser.__name__, len(entries))
            return entries

    return []
