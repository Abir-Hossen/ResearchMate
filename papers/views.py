from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PaperUploadForm
from .models import Paper
from .services import (
    build_workspace_context,
    extract_pdf_content,
    get_paper_metadata,
    get_user_paper,
    process_mock_ai,
)
from .utils import format_file_size


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
    extract_pdf_content(paper)
    process_mock_ai(paper)
    messages.success(request, 'Paper is prepared for AI learning.')
    return redirect('paper_overview', paper_id=paper.id)


@login_required(login_url='login')
def paper_beginner(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'beginner')
    return render(request, 'papers/workspace/beginner.html', context)


@login_required(login_url='login')
def paper_technical(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'technical')
    return render(request, 'papers/workspace/technical.html', context)


@login_required(login_url='login')
def paper_sections(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'sections')
    return render(request, 'papers/workspace/sections.html', context)


@login_required(login_url='login')
def paper_glossary(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'glossary')
    return render(request, 'papers/workspace/glossary.html', context)


@login_required(login_url='login')
def paper_flashcards(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'flashcards')
    return render(request, 'papers/workspace/flashcards.html', context)


@login_required(login_url='login')
def paper_quiz(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'quiz')
    return render(request, 'papers/workspace/quiz.html', context)


@login_required(login_url='login')
def paper_viva(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'viva')
    return render(request, 'papers/workspace/viva.html', context)


@login_required(login_url='login')
def paper_notes(request, paper_id):
    context = build_workspace_context(request.user, paper_id, 'notes')
    return render(request, 'papers/workspace/notes.html', context)
