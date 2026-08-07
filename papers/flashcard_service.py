import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import Flashcard, LearningProgress, PaperContent
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response


class FlashcardGenerationError(ValueError):
    """Raised when flashcard generation fails."""


def _normalize_importance(value):
    if isinstance(value, str):
        value = [item.strip() for item in re.split(r'\n|\r|\u2022|\-|•', value) if item.strip()]
    elif isinstance(value, (list, tuple)):
        value = [str(item).strip() for item in value if str(item).strip()]
    else:
        value = [str(value).strip()] if value is not None else []
    return value


def _clean_flashcards_entries(raw_entries):
    cleaned = []
    seen_questions = set()
    for index, entry in enumerate(raw_entries, start=1):
        if not isinstance(entry, dict):
            continue

        question = str(entry.get('question') or '').strip()
        answer = str(entry.get('answer') or '').strip()
        paper_context = str(entry.get('paper_context') or '').strip()
        importance = _normalize_importance(entry.get('importance') or entry.get('importance_points') or entry.get('why_it_matters'))
        category = str(entry.get('category') or '').strip()
        difficulty = str(entry.get('difficulty') or '').strip()

        if not question or not answer or not category or not difficulty:
            continue

        question_key = question.lower()
        if question_key in seen_questions:
            continue

        seen_questions.add(question_key)
        cleaned.append({
            'question': question,
            'answer': answer,
            'paper_context': paper_context,
            'importance': importance,
            'category': category,
            'difficulty': difficulty,
            'display_order': index,
        })

    return cleaned


def generate_flashcards(paper):
    """Generate paper-specific flashcards from stored extracted text and persist them."""
    try:
        content = paper.content
    except ObjectDoesNotExist as exc:
        raise FlashcardGenerationError('Paper content must exist before generating flashcards.') from exc

    if not content.extracted_text or not content.extracted_text.strip():
        raise FlashcardGenerationError('Paper content must contain extracted text before generating flashcards.')

    existing = list(paper.flashcards.all().order_by('display_order', 'id'))
    if existing:
        return existing

    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        raw_response = ai_service.generate_feature('flashcards', content.extracted_text)
    except Exception as exc:
        raise FlashcardGenerationError('Flashcard generation failed. Please try again later.') from exc

    if not raw_response or not str(raw_response).strip():
        raise FlashcardGenerationError('The AI provider returned an empty flashcards response.')

    valid, payload, error_message = validate_json_response(raw_response)
    if not valid:
        raise FlashcardGenerationError(f'The AI provider returned an invalid JSON response: {error_message}')

    raw_flashcards = payload.get('flashcards')
    if not isinstance(raw_flashcards, list):
        raise FlashcardGenerationError('The AI provider response did not include a valid flashcards list.')

    cleaned_entries = _clean_flashcards_entries(raw_flashcards)
    if not cleaned_entries:
        raise FlashcardGenerationError('The AI provider returned an invalid or empty flashcards payload.')

    Flashcard.objects.filter(paper=paper).delete()
    created_cards = []
    for entry in cleaned_entries:
        created_cards.append(Flashcard.objects.create(
            paper=paper,
            question=entry['question'],
            answer=entry['answer'],
            paper_context=entry['paper_context'],
            importance='\n'.join(entry['importance']),
            category=entry['category'],
            difficulty=entry['difficulty'],
            display_order=entry['display_order'],
        ))

    progress, _ = LearningProgress.objects.get_or_create(paper=paper)
    progress.flashcards_completed = True
    progress.last_accessed = timezone.now()
    progress.save(update_fields=['flashcards_completed', 'last_accessed'])

    return created_cards
