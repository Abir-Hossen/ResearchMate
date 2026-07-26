from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import Paper


class PaperUploadTests(TestCase):
    def test_upload_page_requires_login(self):
        response = self.client.get(reverse('upload_paper'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_user_can_upload_pdf(self):
        user = User.objects.create_user(username='paperuser', password='Secret123')
        self.client.force_login(user)
        pdf = SimpleUploadedFile('sample.pdf', b'%PDF-1.4\n', content_type='application/pdf')

        response = self.client.post(
            reverse('upload_paper'),
            {'title': 'Sample Paper', 'pdf_file': pdf},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Paper.objects.filter(owner=user, title='Sample Paper').exists())
        self.assertContains(response, 'Paper uploaded successfully')
        self.assertRedirects(response, reverse('dashboard'))

    def test_invalid_file_type_is_rejected(self):
        user = User.objects.create_user(username='paperuser2', password='Secret123')
        self.client.force_login(user)
        txt = SimpleUploadedFile('sample.txt', b'hello', content_type='text/plain')

        response = self.client.post(
            reverse('upload_paper'),
            {'title': 'Bad File', 'pdf_file': txt},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only PDF files are allowed.')
