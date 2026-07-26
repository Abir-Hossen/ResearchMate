from django.urls import path

from .views import delete_paper_view, my_papers_view, upload_paper_view

urlpatterns = [
    path('upload/', upload_paper_view, name='upload_paper'),
    path('my-papers/', my_papers_view, name='my_papers'),
    path('delete/<int:pk>/', delete_paper_view, name='delete_paper'),
]
