from django.contrib import admin
from django.utils.html import format_html

from .models import Paper, PaperContent


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
