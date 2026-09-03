from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from .dashboard_service import get_completion_percentage, is_paper_completed
from .models import (
    AIAnalysis,
    Flashcard,
    Glossary,
    LearningProgress,
    Paper,
    PaperContent,
    QuizQuestion,
    Review,
    VivaQuestion,
)


def get_platform_metrics():
    user_model = get_user_model()
    total_users = user_model.objects.count()
    total_papers = Paper.objects.count()
    papers_processed = Paper.objects.filter(processing_status='Completed').count()
    failed_ai_jobs = AIAnalysis.objects.filter(analysis_status='Failed').count()

    if total_papers:
        average_completion = round(
            sum(get_completion_percentage(paper) for paper in Paper.objects.all()) / total_papers,
            1,
        )
    else:
        average_completion = 0

    return {
        'total_users': total_users,
        'total_papers': total_papers,
        'papers_processed': papers_processed,
        'failed_ai_jobs': failed_ai_jobs,
        'average_completion': average_completion,
    }


_original_admin_index = admin.site.index


def _platform_metrics_admin_index(request, extra_context=None):
    if extra_context is None:
        extra_context = {}
    extra_context.update(get_platform_metrics())
    return _original_admin_index(request, extra_context=extra_context)


admin.site.index = _platform_metrics_admin_index


class AIAnalysisInline(admin.StackedInline):
    model = AIAnalysis
    extra = 0
    can_delete = False
    fields = ('analysis_status', 'ai_model', 'generated_at', 'last_updated')
    readonly_fields = ('generated_at', 'last_updated')
    max_num = 1


class GlossaryInline(admin.TabularInline):
    model = Glossary
    extra = 0
    can_delete = False
    fields = ('term', 'display_order', 'paper_role', 'record_action')
    readonly_fields = ('paper_role', 'record_action')
    show_change_link = False
    ordering = ('display_order', 'id')

    def record_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = obj.get_admin_url() if hasattr(obj, 'get_admin_url') else f"/admin/papers/glossary/{obj.pk}/change/"
        return format_html('<a href="{}">View</a>', url)
    record_action.short_description = 'Action'


class FlashcardInline(admin.TabularInline):
    model = Flashcard
    extra = 0
    can_delete = False
    fields = ('question', 'category', 'difficulty', 'display_order', 'record_action')
    readonly_fields = ('record_action',)
    show_change_link = False
    ordering = ('display_order', 'id')

    def record_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = obj.get_admin_url() if hasattr(obj, 'get_admin_url') else f"/admin/papers/flashcard/{obj.pk}/change/"
        return format_html('<a href="{}">View</a>', url)
    record_action.short_description = 'Action'


class QuizQuestionInline(admin.TabularInline):
    model = QuizQuestion
    extra = 0
    can_delete = False
    fields = ('question', 'difficulty', 'correct_answer', 'display_order', 'record_action')
    readonly_fields = ('record_action',)
    show_change_link = False
    ordering = ('display_order', 'id')

    def record_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = obj.get_admin_url() if hasattr(obj, 'get_admin_url') else f"/admin/papers/quizquestion/{obj.pk}/change/"
        return format_html('<a href="{}">View</a>', url)
    record_action.short_description = 'Action'


class VivaQuestionInline(admin.TabularInline):
    model = VivaQuestion
    extra = 0
    can_delete = False
    fields = ('question', 'category', 'difficulty', 'display_order', 'record_action')
    readonly_fields = ('record_action',)
    show_change_link = False
    ordering = ('display_order', 'id')

    def record_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = obj.get_admin_url() if hasattr(obj, 'get_admin_url') else f"/admin/papers/vivaquestion/{obj.pk}/change/"
        return format_html('<a href="{}">View</a>', url)
    record_action.short_description = 'Action'


class LearningProgressInline(admin.StackedInline):
    model = LearningProgress
    extra = 0
    can_delete = False
    fields = ('overall_progress', 'overview_completed', 'beginner_completed', 'technical_completed', 'glossary_completed', 'flashcards_completed', 'quiz_completed', 'viva_completed', 'notes_completed', 'last_accessed')
    readonly_fields = ('last_accessed',)
    max_num = 1


class PaperContentInline(admin.StackedInline):
    model = PaperContent
    extra = 0
    can_delete = False
    fields = ('extraction_status', 'page_count', 'extracted_at', 'extracted_text_display')
    readonly_fields = ('extracted_at', 'extracted_text_display')
    max_num = 1

    def extracted_text_display(self, obj):
        if not obj.extracted_text:
            return 'No extracted text available.'
        return format_html(
            '<textarea readonly rows="12" style="width: 100%; box-sizing: border-box;">{}</textarea>',
            obj.extracted_text,
        )
    extracted_text_display.short_description = 'Extracted Text'


class ViewOnlyGeneratedContentAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    change_form_template = 'admin/papers/paper/change_form.html'
    list_display = ('title', 'owner', 'uploaded_at', 'processing_status', 'ai_analysis_status', 'learning_completion', 'last_accessed')
    list_filter = ('processing_status', 'owner__is_active', 'uploaded_at', 'ai_analysis__analysis_status', 'ai_analysis__ai_model')
    search_fields = ('title', 'owner__username', 'owner__email', 'ai_analysis__analysis_status')
    ordering = ('-uploaded_at',)
    date_hierarchy = 'uploaded_at'
    list_per_page = 25
    autocomplete_fields = ['owner']
    readonly_fields = ('uploaded_at', 'learning_completion', 'last_accessed')
    inlines = [PaperContentInline, AIAnalysisInline, GlossaryInline, FlashcardInline, QuizQuestionInline, VivaQuestionInline, LearningProgressInline]
    fieldsets = (
        ('General Information', {'fields': ('title', 'owner', 'pdf_file')}),
        ('Processing Information', {'fields': ('uploaded_at', 'processing_status', 'learning_completion', 'last_accessed')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('owner', 'ai_analysis', 'learning_progress')

    def ai_analysis_status(self, obj):
        if not obj or not obj.ai_analysis:
            return 'Pending'
        return obj.ai_analysis.analysis_status
    ai_analysis_status.short_description = 'AI Analysis Status'

    def learning_completion(self, obj):
        return get_completion_percentage(obj) if obj else 0
    learning_completion.short_description = 'Learning Completion %'

    def last_accessed(self, obj):
        return getattr(obj.learning_progress, 'last_accessed', None)
    last_accessed.short_description = 'Last Updated'


@admin.register(PaperContent)
class PaperContentAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'extraction_status', 'page_count', 'extracted_at', 'extracted_text_preview')
    list_filter = ('extraction_status', 'extracted_at')
    search_fields = ('paper__title', 'paper__owner__username', 'paper__owner__email')
    ordering = ('-extracted_at',)
    readonly_fields = ('extracted_at', 'extracted_text_display')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper',)}),
        ('Processing Information', {'fields': ('extraction_status', 'extracted_at', 'page_count')}),
        ('Extracted Content', {'fields': ('extracted_text_display',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

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
            '<textarea readonly rows="12" style="width: 100%; box-sizing: border-box;">{}</textarea>',
            obj.extracted_text,
        )
    extracted_text_display.short_description = 'Full Extracted Text'


@admin.register(AIAnalysis)
class AIAnalysisAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'paper_owner', 'analysis_status', 'ai_model', 'generated_at', 'last_updated', 'overview_preview')
    list_filter = ('analysis_status', 'ai_model', 'paper__processing_status', 'generated_at', 'last_updated')
    search_fields = ('paper__title', 'paper__owner__username', 'paper__owner__email', 'analysis_status', 'ai_model')
    ordering = ('-last_updated',)
    readonly_fields = ('paper', 'overview', 'beginner_explanation', 'technical_explanation', 'revision_notes', 'key_contributions', 'key_concepts', 'reading_difficulty_level', 'reading_difficulty_reason', 'analysis_status', 'ai_model', 'analysis_error_display', 'raw_response_display', 'generated_at', 'last_updated')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'overview')}),
        ('Processing Information', {'fields': ('analysis_status', 'ai_model', 'generated_at', 'last_updated')}),
        ('Detailed Analysis', {'fields': ('beginner_explanation', 'technical_explanation', 'revision_notes', 'key_contributions', 'key_concepts', 'reading_difficulty_level', 'reading_difficulty_reason')}),
        ('System Details', {'fields': ('analysis_error_display', 'raw_response_display')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def paper_owner(self, obj):
        return obj.paper.owner if obj and obj.paper else ''
    paper_owner.short_description = 'Owner'

    def overview_preview(self, obj):
        if not obj.overview:
            return 'No overview available.'
        preview = obj.overview[:120]
        return preview + ('...' if len(obj.overview) > 120 else '')
    overview_preview.short_description = 'Overview Preview'

    def analysis_error_display(self, obj):
        return obj.analysis_error or 'No error recorded.'
    analysis_error_display.short_description = 'Analysis Error'

    def raw_response_display(self, obj):
        if not obj.raw_response:
            return 'No raw response captured.'
        return format_html(
            '<textarea readonly rows="8" style="width: 100%; box-sizing: border-box;">{}</textarea>',
            obj.raw_response,
        )
    raw_response_display.short_description = 'Raw Response'


@admin.register(Glossary)
class GlossaryAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'term', 'display_order', 'explanation_preview')
    list_filter = ('paper',)
    search_fields = ('paper__title', 'term', 'paper__owner__username', 'paper__owner__email')
    ordering = ('paper__title', 'display_order', 'id')
    readonly_fields = ('paper', 'term', 'explanation', 'paper_role', 'simple_explanation', 'technical_explanation', 'example', 'display_order', 'created_at')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'term', 'display_order')}),
        ('Content', {'fields': ('explanation', 'paper_role', 'simple_explanation', 'technical_explanation', 'example')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def explanation_preview(self, obj):
        text = obj.explanation or obj.paper_role or obj.simple_explanation or obj.technical_explanation or ''
        if not text:
            return 'No explanation.'
        preview = text[:100]
        return preview + ('...' if len(text) > 100 else '')
    explanation_preview.short_description = 'Explanation Preview'


@admin.register(Flashcard)
class FlashcardAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'category', 'difficulty', 'question_preview')
    list_filter = ('paper', 'category', 'difficulty')
    search_fields = ('paper__title', 'question', 'paper__owner__username', 'paper__owner__email')
    ordering = ('paper__title', 'display_order', 'id')
    readonly_fields = ('paper', 'question', 'answer', 'paper_context', 'importance', 'category', 'difficulty', 'display_order')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'category', 'difficulty', 'display_order')}),
        ('Content', {'fields': ('question', 'answer', 'paper_context', 'importance')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def question_preview(self, obj):
        preview = obj.question[:100]
        return preview + ('...' if len(obj.question) > 100 else '')
    question_preview.short_description = 'Question'


@admin.register(QuizQuestion)
class QuizQuestionAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'difficulty', 'correct_answer', 'question_preview')
    list_filter = ('paper', 'difficulty')
    search_fields = ('paper__title', 'question', 'correct_answer', 'paper__owner__username', 'paper__owner__email')
    ordering = ('paper__title', 'display_order', 'id')
    readonly_fields = ('paper', 'question', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer', 'explanation', 'difficulty', 'display_order')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'difficulty', 'display_order')}),
        ('Question Content', {'fields': ('question', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer', 'explanation')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def question_preview(self, obj):
        preview = obj.question[:100]
        return preview + ('...' if len(obj.question) > 100 else '')
    question_preview.short_description = 'Question'


@admin.register(VivaQuestion)
class VivaQuestionAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'category', 'difficulty', 'question_preview')
    list_filter = ('paper', 'category', 'difficulty')
    search_fields = ('paper__title', 'question', 'paper__owner__username', 'paper__owner__email')
    ordering = ('paper__title', 'display_order', 'id')
    readonly_fields = ('paper', 'question', 'suggested_answer', 'follow_up_question', 'difficulty', 'category', 'examiner_tip', 'display_order')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'category', 'difficulty', 'display_order')}),
        ('Content', {'fields': ('question', 'suggested_answer', 'follow_up_question', 'examiner_tip')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def question_preview(self, obj):
        preview = obj.question[:100]
        return preview + ('...' if len(obj.question) > 100 else '')
    question_preview.short_description = 'Question'


@admin.register(LearningProgress)
class LearningProgressAdmin(ViewOnlyGeneratedContentAdmin):
    list_display = ('id', 'paper', 'paper_owner', 'overall_progress', 'last_accessed', 'module_status_summary')
    list_filter = ('overall_progress', 'last_accessed', 'overview_completed', 'beginner_completed', 'technical_completed', 'glossary_completed', 'flashcards_completed', 'quiz_completed', 'viva_completed', 'notes_completed')
    search_fields = ('paper__title', 'paper__owner__username', 'paper__owner__email')
    ordering = ('-last_accessed', 'paper__title')
    autocomplete_fields = ['paper']
    fieldsets = (
        ('General Information', {'fields': ('paper', 'overall_progress', 'last_accessed')}),
        ('Progress Status', {'fields': ('overview_completed', 'beginner_completed', 'technical_completed', 'glossary_completed', 'flashcards_completed', 'quiz_completed', 'viva_completed', 'notes_completed')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('paper', 'paper__owner')

    def paper_owner(self, obj):
        return obj.paper.owner if obj and obj.paper else ''
    paper_owner.short_description = 'Owner'

    def module_status_summary(self, obj):
        completed = [
            label for label, value in (
                ('Overview', obj.overview_completed),
                ('Beginner', obj.beginner_completed),
                ('Technical', obj.technical_completed),
                ('Glossary', obj.glossary_completed),
                ('Flashcards', obj.flashcards_completed),
                ('Quiz', obj.quiz_completed),
                ('Viva', obj.viva_completed),
                ('Notes', obj.notes_completed),
            ) if value
        ]
        return f'{len(completed)}/8 complete' if completed else '0/8 complete'
    module_status_summary.short_description = 'Module Status'


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('user', 'rating', 'comment_preview', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'rating', 'created_at')
    search_fields = ('user__username', 'user__email', 'comment')
    ordering = ('-created_at',)
    list_editable = ('is_approved',)
    actions = ['admin_approve_reviews', 'admin_reject_reviews']
    readonly_fields = ('user', 'rating', 'comment', 'created_at')

    @admin.action(description='Approve selected reviews')
    def admin_approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)

    @admin.action(description='Reject selected reviews')
    def admin_reject_reviews(self, request, queryset):
        queryset.update(is_approved=False)

    def comment_preview(self, obj):
        return (obj.comment[:120] + '...') if len(obj.comment) > 120 else obj.comment
    comment_preview.short_description = 'Comment'


admin.site.site_header = 'ResearchMate Administration'
admin.site.site_title = 'ResearchMate Admin'
admin.site.index_title = 'Administration'
