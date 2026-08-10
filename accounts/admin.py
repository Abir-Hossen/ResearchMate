from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from django.utils.html import format_html

from papers.dashboard_service import get_completion_percentage, is_paper_completed
from papers.models import LearningProgress, Paper

User = get_user_model()


class PaperInline(admin.TabularInline):
    model = Paper
    fk_name = 'owner'
    extra = 0
    can_delete = False
    fields = ('title', 'uploaded_at', 'processing_status', 'paper_action')
    readonly_fields = ('uploaded_at', 'paper_action')
    show_change_link = False
    ordering = ('-uploaded_at',)

    def paper_action(self, obj):
        if not obj or not obj.pk:
            return '-'
        url = reverse('admin:papers_paper_change', args=[obj.pk])
        return format_html('<a href="{}">View</a>', url)
    paper_action.short_description = 'Action'

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.base_fields['title'].label = 'Paper'
        return formset


class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'account_status', 'is_staff', 'paper_count', 'date_joined', 'last_login')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    list_filter = ('is_staff', 'is_active', 'date_joined')
    ordering = ('-date_joined',)
    readonly_fields = ('last_login', 'date_joined', 'total_uploaded_papers', 'completed_papers', 'papers_in_progress')
    inlines = [PaperInline]
    actions = ['activate_users', 'deactivate_users']

    fieldsets = (
        ('User Overview', {
            'fields': ('username', 'email', 'date_joined', 'last_login', 'total_uploaded_papers', 'completed_papers', 'papers_in_progress')
        }),
        (None, {'fields': ('password',)}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Account Status', {'fields': ('is_active',)}),
        ('Permissions', {'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
    )

    def account_status(self, obj):
        return 'Active' if obj.is_active else 'Deactivated'
    account_status.short_description = 'Account Status'
    account_status.admin_order_field = 'is_active'

    def paper_count(self, obj):
        return obj.papers.count()
    paper_count.short_description = 'Papers'

    def total_uploaded_papers(self, obj):
        return obj.papers.count()
    total_uploaded_papers.short_description = 'Total Papers'

    def completed_papers(self, obj):
        papers = Paper.objects.filter(owner=obj).select_related('ai_analysis', 'learning_progress').prefetch_related('section_learning_sections', 'glossary_terms', 'flashcards', 'quiz_questions', 'viva_questions')
        return sum(1 for paper in papers if is_paper_completed(paper))
    completed_papers.short_description = 'Completed Papers'

    def papers_in_progress(self, obj):
        papers = Paper.objects.filter(owner=obj).select_related('ai_analysis', 'learning_progress').prefetch_related('section_learning_sections', 'glossary_terms', 'flashcards', 'quiz_questions', 'viva_questions')
        return sum(1 for paper in papers if 0 < get_completion_percentage(paper) < 100)
    papers_in_progress.short_description = 'Papers In Progress'

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        queryset.update(is_active=False)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
