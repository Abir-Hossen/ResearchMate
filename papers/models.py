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
