from django import forms
from pathlib import Path
import re

from .models import Paper


class PaperUploadForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    class Meta:
        model = Paper
        fields = ('title', 'pdf_file')
        labels = {
            'title': 'Paper Title',
            'pdf_file': 'PDF File',
        }
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'pdf_file': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.pdf,application/pdf'}),
        }

    def clean_title(self):
        title = self.cleaned_data.get('title')
        if self.user and Paper.objects.filter(owner=self.user, title__iexact=title).exists():
            raise forms.ValidationError('You already have a paper with this title.')
        return title

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if not pdf_file:
            raise forms.ValidationError('Please choose a PDF file to upload.')

        if pdf_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('File is too large. Maximum size is 10MB.')

        if not pdf_file.name.lower().endswith('.pdf'):
            raise forms.ValidationError('Only PDF files are allowed.')

        filename = Path(pdf_file.name).name
        filename_stem = Path(filename).stem.casefold()
        filename_suffix = Path(filename).suffix.casefold()
        if self.user:
            existing_filenames = Paper.objects.filter(owner=self.user).values_list('pdf_file', flat=True)
            if any(
                Path(existing_name).name.casefold() == filename.casefold()
                or (
                    Path(existing_name).suffix.casefold() == filename_suffix
                    and re.fullmatch(rf'{re.escape(filename_stem)}_[a-z0-9]+', Path(existing_name).stem.casefold())
                )
                for existing_name in existing_filenames
            ):
                raise forms.ValidationError('You already have a paper with this file name.')

        return pdf_file
