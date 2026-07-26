from django.urls import path

from .views import upload_paper_view

urlpatterns = [
    path('upload/', upload_paper_view, name='upload_paper'),
]
