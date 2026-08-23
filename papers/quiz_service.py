import json
import logging
import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import LearningProgress, PaperContent, QuizQuestion
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response

logger = logging.getLogger(__name__)


class QuizGenerationError(ValueError):
    """Raised when quiz generation fails."""


def _normalize_options(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r'\n|\r|;|\|', value) if item.strip()]
    return []


def _prepare_quiz_text(text):
    if not text:
        return ''
    cleaned = re.sub(r'\s+', ' ', text).strip()
    suffix = ' [truncated]'
    max_len = 5000 - len(suffix)
    if len(cleaned) <= max_len:
        return cleaned
    truncated = cleaned[:max_len]
    if ' ' in truncated:
        truncated = truncated.rsplit(' ', 1)[0]
    return truncated + suffix


def _clean_quiz_entries(raw_entries):
    cleaned = []
    seen_questions = set()
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue

        question = str(entry.get('question') or '').strip()
        options = _normalize_options(entry.get('options') or entry.get('option_choices'))
        correct_answer = entry.get('correct_answer')
        difficulty = str(entry.get('difficulty') or 'Medium').strip() or 'Medium'
        explanation = str(entry.get('explanation') or '').strip()

        if not question or len(options) != 4:
            continue

        if isinstance(correct_answer, str):
            option_index = None
            normalized = correct_answer.strip().lower()
            if normalized in {'a', 'option_a', 'option a'}:
                option_index = 0
            elif normalized in {'b', 'option_b', 'option b'}:
                option_index = 1
            elif normalized in {'c', 'option_c', 'option c'}:
                option_index = 2
            elif normalized in {'d', 'option_d', 'option d'}:
                option_index = 3
            elif normalized in {'1', '2', '3', '4'}:
                option_index = int(normalized) - 1
            correct_answer_value = options[option_index] if option_index is not None else correct_answer
        else:
            correct_answer_value = options[int(correct_answer) - 1] if isinstance(correct_answer, (int, float)) and 1 <= int(correct_answer) <= 4 else ''

        if not correct_answer_value or correct_answer_value not in options:
            continue

        question_key = question.lower()
        if question_key in seen_questions:
            continue

        seen_questions.add(question_key)
        cleaned.append({
            'question': question,
            'option_a': options[0],
            'option_b': options[1],
            'option_c': options[2],
            'option_d': options[3],
            'correct_answer': str(correct_answer_value),
            'explanation': explanation,
            'difficulty': difficulty.title(),
            'display_order': index,
        })

    return cleaned


def _is_rate_limit_error(exc):
    error_text = str(exc).lower()
    markers = (
        'rate limit exceeded',
        'rate-limit exceeded',
        'usage limit exceeded',
        'quota exceeded',
        'exceeded your current quota',
        'too many requests',
        '429',
        'daily token limit',
        'tokens per day',
    )
    return any(marker in error_text for marker in markers)


def _build_minimal_quiz_prompt(extracted_text):
    return f"""Return ONLY valid JSON with exactly 10 quiz questions from the paper text.

Schema:
{{
  "quiz_questions": [
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "correct_answer": "string",
      "explanation": "string",
      "difficulty": "Easy"
    }}
  ]
}}

Rules:
- correct_answer must be one of the 4 option strings exactly.
- Do not include markdown or extra text.

Paper text:
{extracted_text}
"""


def _repair_json(text):
    candidate = text.strip()
    if candidate.startswith('```'):
        candidate = re.sub(r'^```(?:json)?\s*|\s*```$', '', candidate, flags=re.IGNORECASE | re.MULTILINE)

    candidate = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', candidate)
    candidate = candidate.replace('\u0000', '')

    start = candidate.find('{')
    end = candidate.rfind('}')
    if start != -1 and end > start:
        candidate = candidate[start:end + 1]

    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    candidate = re.sub(r'\"\s*\n\s*', '" ', candidate)
    candidate = re.sub(r'\"\s*\r\s*', '" ', candidate)
    candidate = re.sub(r'(?<!\\)\n', ' ', candidate)
    candidate = re.sub(r'(?<!\\)\r', ' ', candidate)

    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    repaired = _escape_unescaped_quotes(candidate)
    try:
        json.loads(repaired)
        return repaired
    except json.JSONDecodeError:
        pass

    return text


def _escape_unescaped_quotes(text):
    result = []
    in_string = False
    escape_next = False
    prev_char = None

    for char in text:
        if escape_next:
            result.append(char)
            escape_next = False
            prev_char = char
            continue

        if char == '\\' and in_string:
            result.append(char)
            escape_next = True
            prev_char = char
            continue

        if char == '"':
            if in_string:
                next_char = None
                result.append(char)
                in_string = False
                prev_char = char
                continue
            else:
                result.append(char)
                in_string = True
                prev_char = char
                continue

        if char == '\n' and in_string:
            result.append(' ')
            prev_char = char
            continue

        if char == '\r' and in_string:
            result.append(' ')
            prev_char = char
            continue

        result.append(char)
        prev_char = char

    return ''.join(result)


def generate_quiz(paper):
    """Generate paper-specific quiz questions from stored extracted text and persist them."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise QuizGenerationError('Paper content must exist before generating a quiz.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise QuizGenerationError('Paper content must contain extracted text before generating a quiz.')

    existing = list(paper.quiz_questions.all().order_by('display_order', 'id'))
    if existing:
        return existing

    provider = ProviderFactory.create_provider()
    ai_service = AIService(provider=provider)

    raw_response = None
    cleaned_entries = []
    attempt_labels = ['default', 'minimal']

    for attempt_index, label in enumerate(attempt_labels):
        if attempt_index == 0:
            truncated_text = _prepare_quiz_text(content.extracted_text)
            try:
                raw_response = ai_service.generate_feature('quiz', truncated_text, max_completion_tokens=2500)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    raise QuizGenerationError('The AI provider has reached its usage limit. Please try again later.') from exc
                raise QuizGenerationError('Quiz generation failed. Please try again later.') from exc
        else:
            short_text = re.sub(r'\s+', ' ', content.extracted_text).strip()[:2500]
            prompt = _build_minimal_quiz_prompt(short_text)
            try:
                raw_response = provider.generate(prompt, max_completion_tokens=2500)
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    raise QuizGenerationError('The AI provider has reached its usage limit. Please try again later.') from exc
                raise QuizGenerationError('Quiz generation failed. Please try again later.') from exc

        if not raw_response or not str(raw_response).strip():
            if attempt_index == len(attempt_labels) - 1:
                raise QuizGenerationError('The AI provider returned an empty quiz response.')
            continue

        valid, payload, error_message = validate_json_response(raw_response)
        if not valid:
            repaired = _repair_json(raw_response)
            valid, payload, error_message = validate_json_response(repaired)
        if not valid:
            if attempt_index == len(attempt_labels) - 1:
                raise QuizGenerationError(f'The AI provider returned an invalid quiz response: {error_message}')
            continue

        raw_questions = payload.get('quiz_questions')
        if not isinstance(raw_questions, list):
            if attempt_index == len(attempt_labels) - 1:
                raise QuizGenerationError('The AI provider response did not include a valid quiz_questions list.')
            continue

        cleaned_entries = _clean_quiz_entries(raw_questions)
        logger.info(
            'Quiz generation attempt %s: raw=%s cleaned=%s',
            label,
            len(raw_questions) if isinstance(raw_questions, list) else 'n/a',
            len(cleaned_entries),
        )

        if len(cleaned_entries) >= 10:
            break

    if len(cleaned_entries) < 10:
        raise QuizGenerationError('The AI provider returned an incomplete quiz response.')

    QuizQuestion.objects.filter(paper=paper).delete()
    created_questions = []
    for entry in cleaned_entries[:10]:
        created_questions.append(QuizQuestion.objects.create(
            paper=paper,
            question=entry['question'],
            option_a=entry['option_a'],
            option_b=entry['option_b'],
            option_c=entry['option_c'],
            option_d=entry['option_d'],
            correct_answer=entry['correct_answer'],
            explanation=entry['explanation'],
            difficulty=entry['difficulty'],
            display_order=entry['display_order'],
        ))

    progress, _ = LearningProgress.objects.get_or_create(paper=paper)
    progress.quiz_completed = True
    progress.last_accessed = timezone.now()
    progress.save(update_fields=['quiz_completed', 'last_accessed'])

    return created_questions
