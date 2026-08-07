import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PaperUploadForm
from .flashcard_service import FlashcardGenerationError, generate_flashcards
from .glossary_service import GlossaryGenerationError, generate_glossary
from .models import Paper
from .quiz_service import QuizGenerationError, generate_quiz
from .viva_service import VivaGenerationError, generate_viva_questions
from .services import (
    _get_user_facing_error_message,
    build_workspace_context,
    extract_pdf_content,
    get_paper_metadata,
    get_user_paper,
    process_mock_ai,
)
from .section_learning_service import SectionLearningError, generate_section_learning
from .technical_service import TechnicalExplanationError, generate_technical_explanation
from .utils import format_file_size
from django.http import HttpResponse
from django.conf import settings
from .groq_connectivity import GroqLearningService

logger = logging.getLogger(__name__)


@login_required(login_url='login')
def upload_paper_view(request):
    if request.method == 'POST':
        form = PaperUploadForm(request.POST, request.FILES)
        if form.is_valid():
            paper = form.save(commit=False)
            paper.owner = request.user
            paper.save()
            messages.success(request, 'Paper uploaded successfully.')
            return redirect('dashboard')
    else:
        form = PaperUploadForm()

    return render(request, 'papers/upload.html', {'form': form})


@login_required(login_url='login')
def my_papers_view(request):
    query = request.GET.get('q', '').strip()
    papers = Paper.objects.filter(owner=request.user).order_by('-uploaded_at')

    if query:
        papers = papers.filter(title__icontains=query)

    return render(request, 'papers/library.html', {'papers': papers, 'query': query})


@login_required(login_url='login')
def delete_paper_view(request, pk):
    paper = get_object_or_404(Paper, pk=pk, owner=request.user)

    if request.method == 'POST':
        if paper.pdf_file:
            paper.pdf_file.delete(save=False)
        paper.delete()
        messages.success(request, 'Paper deleted successfully.')
        return redirect('my_papers')

    return render(request, 'papers/delete_confirm.html', {'paper': paper})


@login_required(login_url='login')
def paper_overview(request, paper_id):
    paper = get_user_paper(request.user, paper_id)
    metadata = get_paper_metadata(paper)
    metadata.update(build_workspace_context(request.user, paper_id, 'overview'))
    metadata['file_size_display'] = format_file_size(metadata['file_size'])
    return render(request, 'papers/workspace/overview.html', metadata)


@login_required(login_url='login')
def start_learning_view(request, paper_id):
    paper = get_user_paper(request.user, paper_id)
    try:
        try:
            content = paper.content
        except ObjectDoesNotExist:
            content = None

        if content is None or not content.extracted_text or content.extraction_status != 'Ready':
            logger.info('Paper ID %s: Extraction started.', paper.id)
            extract_pdf_content(paper)
            logger.info('Paper ID %s: Extraction completed.', paper.id)
        else:
            logger.info('Paper ID %s: Reusing existing extracted text.', paper.id)

        result = process_mock_ai(paper)
        if getattr(result, 'analysis_status', None) == 'Failed':
            logger.warning('Paper ID %s: AI analysis failed and the workspace will show a retry banner.', paper.id)
        else:
            logger.info('Paper ID %s: Database saved.', paper.id)
            logger.info('Paper ID %s: Learning Hub updated.', paper.id)
            messages.success(request, 'Paper is prepared for AI learning.')
    except Exception as exc:
        logger.exception('Paper ID %s: Learning workflow failed.', paper.id)

    return redirect('paper_beginner', paper_id=paper.id)


@login_required(login_url='login')
def paper_beginner(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'beginner')
    return render(request, 'papers/workspace/beginner.html', context)


@login_required(login_url='login')
def paper_technical(request, paper_id):
    paper = get_user_paper(request.user, paper_id)

    if request.method == 'POST':
        try:
            generate_technical_explanation(paper, force_refresh=True)
            messages.success(request, 'Technical explanation generated successfully.')
        except TechnicalExplanationError as exc:
            logger.warning('Paper ID %s: technical explanation generation failed: %s', paper.id, exc)
            messages.error(request, str(exc))
        return redirect('paper_technical', paper_id=paper.id)

    context = build_workspace_context(request.user, paper_id, 'technical')
    return render(request, 'papers/workspace/technical.html', context)


@login_required(login_url='login')
def paper_sections(request, paper_id):
    paper = get_user_paper(request.user, paper_id)

    if request.method == 'POST':
        try:
            generate_section_learning(paper, force_refresh=True)
            messages.success(request, 'Section Learning generated successfully.')
        except SectionLearningError as exc:
            logger.warning('Paper ID %s: section learning generation failed: %s', paper.id, exc)
            messages.error(request, str(exc))
        return redirect('paper_sections', paper_id=paper.id)

    context = build_workspace_context(request.user, paper_id, 'sections')
    return render(request, 'papers/workspace/sections.html', context)


@login_required(login_url='login')
def paper_glossary(request, paper_id):
    paper = get_user_paper(request.user, paper_id)

    if request.method == 'POST':
        try:
            generate_glossary(paper)
            messages.success(request, 'Glossary generated successfully.')
        except GlossaryGenerationError as exc:
            logger.warning('Paper ID %s: glossary generation failed: %s', paper.id, exc)
            messages.error(request, str(exc))
        return redirect('paper_glossary', paper_id=paper.id)

    context = build_workspace_context(request.user, paper_id, 'glossary')
    return render(request, 'papers/workspace/glossary.html', context)


@login_required(login_url='login')
def paper_flashcards(request, paper_id):
    paper = get_user_paper(request.user, paper_id)

    if request.method == 'POST':
        try:
            generate_flashcards(paper)
            messages.success(request, 'Flashcards generated successfully.')
        except FlashcardGenerationError as exc:
            logger.warning('Paper ID %s: flashcard generation failed: %s', paper.id, exc)
            messages.error(request, str(exc))
        return redirect('paper_flashcards', paper_id=paper.id)

    context = build_workspace_context(request.user, paper_id, 'flashcards')
    return render(request, 'papers/workspace/flashcards.html', context)


@login_required(login_url='login')
def paper_quiz(request, paper_id):
    paper = get_user_paper(request.user, paper_id)
    quiz_questions = list(paper.quiz_questions.all().order_by('display_order', 'id'))
    context = build_workspace_context(request.user, paper_id, 'quiz')
    context['quiz_questions'] = quiz_questions

    if request.method == 'POST':
        action = request.POST.get('action', 'generate')
        if action == 'generate':
            try:
                generate_quiz(paper)
                messages.success(request, 'Quiz generated successfully.')
            except QuizGenerationError as exc:
                logger.warning('Paper ID %s: quiz generation failed: %s', paper.id, exc)
                messages.error(request, str(exc))

            request.session.pop(f'quiz_answers_{paper.id}', None)
            return redirect('paper_quiz', paper_id=paper.id)

        current_index = int(request.POST.get('question_index', 0))
        selected_answer = request.POST.get('selected_answer', '')
        if selected_answer:
            answers = dict(request.session.get(f'quiz_answers_{paper.id}', {}))
            answers[str(current_index)] = selected_answer
            request.session[f'quiz_answers_{paper.id}'] = answers

        if action == 'submit':
            review_rows = []
            for index, question in enumerate(quiz_questions):
                answer = request.session.get(f'quiz_answers_{paper.id}', {}).get(str(index), '')
                review_rows.append({
                    'question': question,
                    'student_answer': answer,
                    'correct_answer': question.correct_answer,
                    'is_correct': answer == question.correct_answer,
                })

            correct_answers = sum(1 for row in review_rows if row['is_correct'])
            total_questions = len(review_rows)
            percentage = round((correct_answers / total_questions) * 100, 1) if total_questions else 0
            context.update({
                'show_results': True,
                'review_rows': review_rows,
                'correct_answers': correct_answers,
                'total_questions': total_questions,
                'percentage': percentage,
                'passed': percentage >= 70,
                'current_question': None,
            })
            return render(request, 'papers/workspace/quiz.html', context)

        if action == 'next':
            current_index += 1
        elif action == 'prev':
            current_index -= 1

        current_index = max(0, min(current_index, len(quiz_questions) - 1)) if quiz_questions else 0
        context['current_question'] = quiz_questions[current_index] if quiz_questions else None
        context['question_index'] = current_index
        context['question_count'] = len(quiz_questions)
        context['selected_answer'] = request.session.get(f'quiz_answers_{paper.id}', {}).get(str(current_index), '')
        return render(request, 'papers/workspace/quiz.html', context)

    if quiz_questions:
        context['current_question'] = quiz_questions[0]
        context['question_index'] = 0
        context['question_count'] = len(quiz_questions)
        context['selected_answer'] = request.session.get(f'quiz_answers_{paper.id}', {}).get('0', '')
    return render(request, 'papers/workspace/quiz.html', context)


@login_required(login_url='login')
def paper_viva(request, paper_id):
    paper = get_user_paper(request.user, paper_id)

    if request.method == 'POST':
        try:
            generate_viva_questions(paper)
            messages.success(request, 'Viva questions generated successfully.')
        except VivaGenerationError as exc:
            logger.warning('Paper ID %s: viva generation failed: %s', paper.id, exc)
            messages.error(request, str(exc))
        return redirect('paper_viva', paper_id=paper.id)

    context = build_workspace_context(request.user, paper_id, 'viva')
    viva_questions = list(paper.viva_questions.all().order_by('display_order', 'id'))
    grouped_viva_questions = {}
    for question in viva_questions:
        category_name = question.category or 'Basic Understanding'
        grouped_viva_questions.setdefault(category_name, []).append(question)

    context['viva_questions'] = viva_questions
    context['grouped_viva_questions'] = grouped_viva_questions
    return render(request, 'papers/workspace/viva.html', context)


@login_required(login_url='login')
def paper_notes(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'notes')
    return render(request, 'papers/workspace/notes.html', context)


def groq_test_view(request):
    """Development-only view that exercises the GroqLearningService.

    URL: /debug/groq-test/
    """
    if not settings.DEBUG:
        return HttpResponse('Not available', status=404)

    try:
        service = GroqLearningService()
    except Exception as exc:
        content = f"Error initializing GroqLearningService:\n{type(exc).__name__}: {exc}"
        return HttpResponse(content, content_type='text/plain', status=500)

    try:
        result = service.test_connection()
    except Exception as exc:
        content = f"Groq request failed:\n{type(exc).__name__}: {exc}"
        return HttpResponse(content, content_type='text/plain', status=500)

    body = [
        f"API key loaded: {bool(settings.GROQ_API_KEY or None)}",
        f"Model name: {result.get('model')}",
        f"Connection successful: Yes",
        f"AI response: {result.get('response')}",
        f"Response time: {result.get('elapsed'):.3f} s",
    ]

    return HttpResponse('\n'.join(body), content_type='text/plain')
