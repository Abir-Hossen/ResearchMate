from django import forms

from .models import Paper


class PaperUploadForm(forms.ModelForm):
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

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if not pdf_file:
            raise forms.ValidationError('Please choose a PDF file to upload.')

        if pdf_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError('File is too large. Maximum size is 10MB.')

        if not pdf_file.name.lower().endswith('.pdf'):
            raise forms.ValidationError('Only PDF files are allowed.')

        return pdf_file
