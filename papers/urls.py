from django.urls import path

from .views import (
    delete_paper_view,
    my_papers_view,
    paper_beginner,
    paper_flashcards,
    paper_glossary,
    paper_notes,
    paper_overview,
    paper_quiz,
    paper_sections,
    paper_technical,
    start_learning_view,
    upload_paper_view,
)

urlpatterns = [
    path('upload/', upload_paper_view, name='upload_paper'),
    path('my-papers/', my_papers_view, name='my_papers'),
    path('delete/<int:pk>/', delete_paper_view, name='delete_paper'),
    path('<int:paper_id>/overview/', paper_overview, name='paper_overview'),
    path('<int:paper_id>/start-learning/', start_learning_view, name='start_learning'),
    path('<int:paper_id>/beginner/', paper_beginner, name='paper_beginner'),
    path('<int:paper_id>/technical/', paper_technical, name='paper_technical'),
    path('<int:paper_id>/sections/', paper_sections, name='paper_sections'),
    path('<int:paper_id>/glossary/', paper_glossary, name='paper_glossary'),
    path('<int:paper_id>/flashcards/', paper_flashcards, name='paper_flashcards'),
    path('<int:paper_id>/quiz/', paper_quiz, name='paper_quiz'),
    path('<int:paper_id>/notes/', paper_notes, name='paper_notes'),
]
