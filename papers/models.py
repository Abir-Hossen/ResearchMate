from django.contrib.auth.models import User
from django.db import models


class Paper(models.Model):
    STATUS_CHOICES = [
        ('Uploaded', 'Uploaded'),
        ('Processing', 'Processing'),
        ('Completed', 'Completed'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='papers')
    title = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to='papers/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Uploaded')

    def __str__(self):
        return self.title

    @property
    def content_status(self):
        try:
            return self.content.extraction_status
        except PaperContent.DoesNotExist:
            return 'Pending'


class PaperContent(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Ready', 'Ready'),
        ('Failed', 'Failed'),
    ]

    paper = models.OneToOneField(Paper, on_delete=models.CASCADE, related_name='content')
    extracted_text = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(default=0)
    extraction_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    extracted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Content for {self.paper.title}'
