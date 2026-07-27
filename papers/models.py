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


class AIAnalysis(models.Model):
    paper = models.OneToOneField(Paper, on_delete=models.CASCADE, related_name='ai_analysis')
    overview = models.TextField(blank=True)
    beginner_explanation = models.TextField(blank=True)
    technical_explanation = models.TextField(blank=True)
    key_contributions = models.TextField(blank=True)
    key_concepts = models.JSONField(default=list, blank=True)
    reading_difficulty_level = models.CharField(max_length=50, blank=True)
    reading_difficulty_reason = models.TextField(blank=True)
    analysis_status = models.CharField(max_length=30, default='Pending', blank=True)
    ai_model = models.CharField(max_length=100, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'AI analysis for {self.paper.title}'


class Glossary(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='glossary_terms')
    term = models.CharField(max_length=255)
    simple_explanation = models.TextField(blank=True)
    technical_explanation = models.TextField(blank=True)
    example = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.term


class Flashcard(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='flashcards')
    question = models.TextField()
    answer = models.TextField()
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.question[:80]


class QuizQuestion(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='quiz_questions')
    question = models.TextField()
    option_a = models.CharField(max_length=255)
    option_b = models.CharField(max_length=255)
    option_c = models.CharField(max_length=255)
    option_d = models.CharField(max_length=255)
    correct_answer = models.CharField(max_length=20)
    explanation = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.question[:80]


class VivaQuestion(models.Model):
    paper = models.ForeignKey(Paper, on_delete=models.CASCADE, related_name='viva_questions')
    question = models.TextField()
    suggested_answer = models.TextField(blank=True)
    follow_up_question = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.question[:80]


class LearningProgress(models.Model):
    paper = models.OneToOneField(Paper, on_delete=models.CASCADE, related_name='learning_progress')
    overview_completed = models.BooleanField(default=False)
    beginner_completed = models.BooleanField(default=False)
    technical_completed = models.BooleanField(default=False)
    glossary_completed = models.BooleanField(default=False)
    flashcards_completed = models.BooleanField(default=False)
    quiz_completed = models.BooleanField(default=False)
    viva_completed = models.BooleanField(default=False)
    notes_completed = models.BooleanField(default=False)
    overall_progress = models.PositiveIntegerField(default=0)
    last_accessed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Progress for {self.paper.title}'
