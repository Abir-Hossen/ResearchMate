import re

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .ai_service import AIService
from .models import LearningProgress, PaperContent, QuizQuestion
from .provider_factory import ProviderFactory
from .response_validator import validate_json_response


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
            correct_answer_value = options[option_index] if option_index is not None else correct_answer
        else:
            correct_answer_value = options[int(correct_answer) - 1] if isinstance(correct_answer, (int, float)) and 1 <= int(correct_answer) <= 4 else ''

        if not correct_answer_value:
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

    try:
        provider = ProviderFactory.create_provider()
        ai_service = AIService(provider=provider)
        raw_response = ai_service.generate_feature('quiz', content.extracted_text)
    except Exception as exc:
        raise QuizGenerationError('Quiz generation failed. Please try again later.') from exc

    if not raw_response or not str(raw_response).strip():
        raise QuizGenerationError('The AI provider returned an empty quiz response.')

    valid, payload, error_message = validate_json_response(raw_response)
    if not valid:
        raise QuizGenerationError(f'The AI provider returned an invalid JSON response: {error_message}')

    raw_questions = payload.get('quiz_questions')
    if not isinstance(raw_questions, list):
        raise QuizGenerationError('The AI provider response did not include a valid quiz_questions list.')

    cleaned_entries = _clean_quiz_entries(raw_questions)
    if not cleaned_entries or len(cleaned_entries) < 10:
        raise QuizGenerationError('The AI provider returned an invalid or incomplete quiz payload.')

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
