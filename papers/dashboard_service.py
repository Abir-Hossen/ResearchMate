from __future__ import annotations

from django.db.models import Avg, Exists, OuterRef

from .models import (
    AIAnalysis,
    Flashcard,
    Glossary,
    Paper,
    PaperSection,
    QuizAttempt,
    QuizQuestion,
    VivaQuestion,
)

TOTAL_MODULES = 8
CONTINUE_LEARNING_LIMIT = 4
RECENT_PAPERS_LIMIT = 4
MODULE_SEQUENCE = (
    ('beginner', 'Beginner Explanation'),
    ('technical', 'Technical Explanation'),
    ('section_learning', 'Section Learning'),
    ('glossary', 'Glossary'),
    ('flashcards', 'Flashcards'),
    ('quiz', 'Quiz'),
    ('viva', 'Viva Preparation'),
    ('notes', 'Study Notes'),
)


def get_module_completion_checks(paper):
    analysis = getattr(paper, 'ai_analysis', None)
    return {
        'beginner': bool(analysis and analysis.beginner_explanation),
        'technical': bool(analysis and analysis.technical_explanation),
        'section_learning': bool(paper.section_learning_sections.exists()),
        'glossary': bool(paper.glossary_terms.exists()),
        'flashcards': bool(paper.flashcards.exists()),
        'quiz': bool(paper.quiz_questions.exists()),
        'viva': bool(paper.viva_questions.exists()),
        'notes': bool(analysis and analysis.revision_notes),
    }


def is_paper_completed(paper):
    """Return True only when every required learning module has been generated."""
    module_checks = get_module_completion_checks(paper)
    return all(module_checks.values())


def get_completion_percentage(paper):
    module_checks = get_module_completion_checks(paper)
    completed = sum(1 for is_complete in module_checks.values() if is_complete)
    return round((completed / TOTAL_MODULES) * 100)


def get_missing_modules(paper):
    module_checks = get_module_completion_checks(paper)
    missing = [label for key, label in MODULE_SEQUENCE if not module_checks.get(key, False)]
    return missing


def get_dashboard_data(user):
    papers = (
        Paper.objects.filter(owner=user)
        .annotate(
            has_analysis=Exists(AIAnalysis.objects.filter(paper_id=OuterRef('pk'))),
            has_beginner=Exists(AIAnalysis.objects.filter(paper_id=OuterRef('pk')).filter(beginner_explanation__gt='')),
            has_technical=Exists(AIAnalysis.objects.filter(paper_id=OuterRef('pk')).filter(technical_explanation__gt='')),
            has_sections=Exists(PaperSection.objects.filter(paper_id=OuterRef('pk'))),
            has_glossary=Exists(Glossary.objects.filter(paper_id=OuterRef('pk'))),
            has_flashcards=Exists(Flashcard.objects.filter(paper_id=OuterRef('pk'))),
            has_quiz=Exists(QuizQuestion.objects.filter(paper_id=OuterRef('pk'))),
            has_viva=Exists(VivaQuestion.objects.filter(paper_id=OuterRef('pk'))),
            has_notes=Exists(AIAnalysis.objects.filter(paper_id=OuterRef('pk')).filter(revision_notes__gt='')),
        )
        .select_related('ai_analysis', 'learning_progress')
        .prefetch_related(
            'glossary_terms',
            'flashcards',
            'quiz_questions',
            'viva_questions',
            'section_learning_sections',
            'quiz_attempts',
        )
        .order_by('-uploaded_at')
    )

    paper_list = list(papers)
    completed_papers = [paper for paper in paper_list if is_paper_completed(paper)]
    in_progress_papers = [paper for paper in paper_list if not is_paper_completed(paper)]
    continue_learning = in_progress_papers[:CONTINUE_LEARNING_LIMIT]
    recent_papers = paper_list[:RECENT_PAPERS_LIMIT]

    latest_by_paper = {}
    for attempt in QuizAttempt.objects.filter(paper__owner=user).order_by('paper_id', '-completed_at'):
        latest_by_paper.setdefault(attempt.paper_id, attempt)
    latest_attempts = list(latest_by_paper.values())

    average_quiz_score = None
    if latest_attempts:
        average_quiz_score = sum(attempt.percentage for attempt in latest_attempts) / len(latest_attempts)
    average_display = 'No quiz yet'
    if average_quiz_score is not None:
        average_display = f'{int(round(average_quiz_score))}%'

    viva_ready_count = Paper.objects.filter(owner=user).annotate(
        has_viva=Exists(VivaQuestion.objects.filter(paper_id=OuterRef('pk')))
    ).filter(has_viva=True).count()

    dashboard = {
        'total_papers': len(paper_list),
        'papers_in_progress': len(in_progress_papers),
        'completed_papers_count': len(completed_papers),
        'average_quiz_score': average_display,
        'viva_ready_count': viva_ready_count,
        'continue_learning': [
            {
                'paper': paper,
                'title': paper.title,
                'updated_at': paper.uploaded_at,
                'completion_percentage': get_completion_percentage(paper),
                'missing_modules': get_missing_modules(paper),
                'status': 'In Progress',
            }
            for paper in continue_learning
        ],
        'recent_papers': [
            {
                'paper': paper,
                'title': paper.title,
                'uploaded_at': paper.uploaded_at,
                'status': 'Completed' if is_paper_completed(paper) else 'In Progress',
                'completion_percentage': get_completion_percentage(paper),
                'is_completed': is_paper_completed(paper),
            }
            for paper in recent_papers
        ],
        'completed_papers': [
            {
                'paper': paper,
                'title': paper.title,
                'uploaded_at': paper.uploaded_at,
                'status': 'Completed',
                'completion_percentage': get_completion_percentage(paper),
                'is_completed': True,
            }
            for paper in completed_papers[:RECENT_PAPERS_LIMIT]
        ],
        'empty_state': len(paper_list) == 0,
        'no_papers_in_progress': len(in_progress_papers) == 0,
        'no_completed_papers': len(completed_papers) == 0,
        'no_quizzes_completed': not latest_attempts,
        'show_view_all_recent': len(paper_list) > RECENT_PAPERS_LIMIT,
    }

    return dashboard
