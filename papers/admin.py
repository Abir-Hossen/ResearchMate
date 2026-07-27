from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AIAnalysis,
    Flashcard,
    Glossary,
    LearningProgress,
    Paper,
    PaperContent,
    QuizQuestion,
    VivaQuestion,
)


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'owner', 'uploaded_at', 'processing_status')
    search_fields = ('title', 'owner__username')
    list_filter = ('uploaded_at', 'processing_status')
    ordering = ('-uploaded_at',)
    list_per_page = 25

    fieldsets = (
        ('General Information', {
            'fields': ('title', 'owner', 'pdf_file')
        }),
        ('File Information', {
            'fields': ('uploaded_at',)
        }),
        ('Processing Information', {
            'fields': ('processing_status',)
        }),
    )


@admin.register(PaperContent)
class PaperContentAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'extraction_status', 'page_count', 'extracted_at', 'extracted_text_preview')
    search_fields = ('paper__title', 'paper__owner__username')
    list_filter = ('extraction_status', 'extracted_at')
    ordering = ('-extracted_at',)
    readonly_fields = ('extracted_text_display',)
    fieldsets = (
        ('General Information', {
            'fields': ('paper',)
        }),
        ('Processing Information', {
            'fields': ('extraction_status', 'extracted_at', 'page_count')
        }),
        ('Extracted Content', {
            'fields': ('extracted_text_display',)
        }),
    )

    def extracted_text_preview(self, obj):
        if not obj.extracted_text:
            return 'No extracted text yet.'

        preview = obj.extracted_text[:180]
        return preview + ('...' if len(obj.extracted_text) > 180 else '')

    extracted_text_preview.short_description = 'Extracted Text Preview'

    def extracted_text_display(self, obj):
        if not obj.extracted_text:
            return 'No extracted text available.'

        return format_html(
            '<textarea readonly rows="12" cols="100" style="width: 100%;">{}</textarea>',
            obj.extracted_text
        )

    extracted_text_display.short_description = 'Full Extracted Text'


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'analysis_status', 'ai_model', 'last_updated')
    search_fields = ('paper__title', 'paper__owner__username')
    list_filter = ('analysis_status', 'ai_model', 'last_updated')
    ordering = ('-last_updated',)
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'overview')
        }),
        ('Processing Information', {
            'fields': ('analysis_status', 'ai_model', 'generated_at', 'last_updated')
        }),
        ('Detailed Analysis', {
            'fields': ('beginner_explanation', 'technical_explanation', 'key_contributions', 'key_concepts', 'reading_difficulty_level', 'reading_difficulty_reason')
        }),
    )


@admin.register(Glossary)
class GlossaryAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'term', 'display_order')
    search_fields = ('paper__title', 'term')
    list_filter = ('paper', 'display_order')
    ordering = ('paper', 'display_order', 'id')
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'term', 'display_order')
        }),
        ('Content', {
            'fields': ('simple_explanation', 'technical_explanation', 'example')
        }),
    )


@admin.register(Flashcard)
class FlashcardAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'question', 'display_order')
    search_fields = ('paper__title', 'question')
    list_filter = ('paper', 'display_order')
    ordering = ('paper', 'display_order', 'id')
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'display_order')
        }),
        ('Content', {
            'fields': ('question', 'answer')
        }),
    )


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'question', 'correct_answer', 'display_order')
    search_fields = ('paper__title', 'question')
    list_filter = ('paper', 'correct_answer', 'display_order')
    ordering = ('paper', 'display_order', 'id')
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'display_order')
        }),
        ('Question Content', {
            'fields': ('question', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer', 'explanation')
        }),
    )


@admin.register(VivaQuestion)
class VivaQuestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'question', 'display_order')
    search_fields = ('paper__title', 'question')
    list_filter = ('paper', 'display_order')
    ordering = ('paper', 'display_order', 'id')
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'display_order')
        }),
        ('Content', {
            'fields': ('question', 'suggested_answer', 'follow_up_question')
        }),
    )


@admin.register(LearningProgress)
class LearningProgressAdmin(admin.ModelAdmin):
    list_display = ('id', 'paper', 'overall_progress', 'last_accessed')
    search_fields = ('paper__title',) 
    list_filter = ('overall_progress', 'last_accessed')
    ordering = ('-last_accessed',)
    fieldsets = (
        ('General Information', {
            'fields': ('paper', 'overall_progress', 'last_accessed')
        }),
        ('Progress Status', {
            'fields': ('overview_completed', 'beginner_completed', 'technical_completed', 'glossary_completed', 'flashcards_completed', 'quiz_completed', 'viva_completed', 'notes_completed')
        }),
    )