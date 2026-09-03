import logging
import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import LearningProgress, PaperContent, VivaQuestion
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response

logger = logging.getLogger(__name__)


class VivaGenerationError(ValueError):
    """Raised when viva question generation fails."""


def _repair_viva_json(text):
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


def _normalize_answers(value):
    if isinstance(value, str):
        return [item.strip() for item in re.split(r'\n|\r|;|\|', value) if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _clean_viva_entries(raw_entries):
    cleaned = []
    seen_questions = set()
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue

        question = str(entry.get('question') or '').strip()
        answer = str(entry.get('answer') or entry.get('suggested_answer') or '').strip()
        difficulty = str(entry.get('difficulty') or 'Medium').strip() or 'Medium'
        category = str(entry.get('category') or 'Basic').strip() or 'Basic'
        examiner_tip = str(entry.get('examiner_tip') or entry.get('follow_up_question') or '').strip()

        if not question or not answer:
            continue

        if question.lower() in seen_questions:
            continue

        seen_questions.add(question.lower())
        cleaned.append({
            'question': question,
            'suggested_answer': answer,
            'follow_up_question': '',
            'difficulty': difficulty.title(),
            'category': category,
            'examiner_tip': examiner_tip,
            'display_order': index,
        })

    return cleaned


def _generate_with_retry(paper, provider, ai_service, max_attempts=2):
    """Attempt viva generation with focused prompt, retrying once on malformed JSON."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            raw_response = ai_service.generate_feature('viva', paper.content.extracted_text)
        except Exception as exc:
            last_error = exc
            logger.warning('Viva generation attempt %d failed: %s', attempt + 1, exc)
            continue

        if not raw_response or not str(raw_response).strip():
            last_error = ValueError('Empty viva response')
            logger.warning('Viva generation attempt %d returned empty response.', attempt + 1)
            continue

        valid, payload, error_message = validate_json_response(raw_response)
        if not valid:
            repaired = _repair_viva_json(raw_response)
            valid, payload, error_message = validate_json_response(repaired)

        if valid:
            return payload

        last_error = ValueError(f'Invalid JSON: {error_message}')
        logger.warning(
            'Viva generation attempt %d returned invalid JSON: %s',
            attempt + 1,
            error_message,
        )

    raise VivaGenerationError('Viva question generation failed. Please try again later.') from last_error


def generate_viva_questions(paper):
    """Generate paper-specific viva questions from stored extracted text and persist them."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise VivaGenerationError('Paper content must exist before generating viva questions.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise VivaGenerationError('Paper content must contain extracted text before generating viva questions.')

    existing = list(paper.viva_questions.all().order_by('display_order', 'id'))
    if existing:
        return existing

    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        payload = _generate_with_retry(paper, provider, ai_service)
    except VivaGenerationError:
        raise
    except Exception as exc:
        raise VivaGenerationError('Viva question generation failed. Please try again later.') from exc

    raw_questions = payload.get('viva_questions')
    if not isinstance(raw_questions, list):
        raise VivaGenerationError('The AI provider response did not include a valid viva_questions list.')

    cleaned_entries = _clean_viva_entries(raw_questions)
    if not cleaned_entries or len(cleaned_entries) < 8:
        raise VivaGenerationError('The AI provider returned an invalid or incomplete viva payload.')

    VivaQuestion.objects.filter(paper=paper).delete()
    created_questions = []
    for entry in cleaned_entries[:15]:
        created_questions.append(VivaQuestion.objects.create(
            paper=paper,
            question=entry['question'],
            suggested_answer=entry['suggested_answer'],
            follow_up_question=entry['follow_up_question'],
            difficulty=entry['difficulty'],
            category=entry['category'],
            examiner_tip=entry['examiner_tip'],
            display_order=entry['display_order'],
        ))

    progress, _ = LearningProgress.objects.get_or_create(paper=paper)
    progress.viva_completed = True
    progress.last_accessed = timezone.now()
    progress.save(update_fields=['viva_completed', 'last_accessed'])

    return created_questions
