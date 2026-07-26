from django.shortcuts import get_object_or_404

from .models import Paper


def get_user_paper(user, paper_id):
    return get_object_or_404(Paper, pk=paper_id, owner=user)


def get_paper_metadata(paper):
    return {
        'paper': paper,
        'title': paper.title,
        'uploaded_at': paper.uploaded_at,
        'status': paper.processing_status,
        'file_name': paper.pdf_file.name.split('/')[-1],
        'file_size': paper.pdf_file.size,
    }


def build_workspace_context(user, paper_id, active_tab):
    paper = get_user_paper(user, paper_id)
    return {
        'paper': paper,
        'active_tab': active_tab,
    }
