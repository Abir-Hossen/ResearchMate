from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User

from papers.dashboard_service import get_dashboard_data, is_paper_completed
from papers.models import AIAnalysis, Flashcard, Glossary, LearningProgress, Paper, PaperSection, QuizAttempt, QuizQuestion, VivaQuestion


class AuthenticationFlowTests(TestCase):
    def test_register_creates_new_user_and_redirects_to_login(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'Ada Lovelace',
                'username': 'ada',
                'email': 'ada@example.com',
                'password1': 'StrongPass123',
                'password2': 'StrongPass123',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='ada').exists())
        self.assertContains(response, 'Account created successfully')
        self.assertRedirects(response, reverse('login'))

    def test_login_redirects_to_dashboard_for_authenticated_user(self):
        User.objects.create_user(username='tester', email='tester@example.com', password='Secret123')
        response = self.client.post(
            reverse('login'),
            {'username': 'tester', 'password': 'Secret123'},
            follow=True,
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.assertContains(response, 'Welcome back')

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(username='existing', email='existing@example.com', password='Secret123')
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'New User',
                'username': 'newuser',
                'email': 'existing@example.com',
                'password1': 'StrongPass123',
                'password2': 'StrongPass123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_authenticated_user_sees_dashboard_sections(self):
        user = User.objects.create_user(username='dashuser', email='dash@example.com', password='Secret123')
        Paper.objects.create(owner=user, title='Alpha Paper', pdf_file='papers/alpha.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total Papers')
        self.assertContains(response, 'Papers In Progress')
        self.assertContains(response, 'Average Quiz Score')
        self.assertContains(response, 'Viva Ready')
        self.assertContains(response, 'Continue Learning')
        self.assertContains(response, 'Recent Papers')

    def test_dashboard_shows_empty_state_for_no_papers(self):
        user = User.objects.create_user(username='emptydash', email='emptydash@example.com', password='Secret123')
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You haven't uploaded any research papers yet.")
        self.assertContains(response, 'Upload your first paper to begin learning.')

    def test_dashboard_calculates_student_metrics(self):
        user = User.objects.create_user(username='metricuser', email='metric@example.com', password='Secret123')
        self.client.force_login(user)

        completed_paper = Paper.objects.create(owner=user, title='Completed Study', pdf_file='papers/test.pdf')
        AIAnalysis.objects.create(
            paper=completed_paper,
            beginner_explanation='Beginner overview',
            technical_explanation='Technical overview',
            revision_notes='Notes',
        )
        Glossary.objects.create(paper=completed_paper, term='Model', explanation='A model is a representation')
        Flashcard.objects.create(paper=completed_paper, question='Q?', answer='A')
        QuizQuestion.objects.create(
            paper=completed_paper,
            question='Why?',
            option_a='A',
            option_b='B',
            option_c='C',
            option_d='D',
            correct_answer='A',
        )
        VivaQuestion.objects.create(paper=completed_paper, question='Explain it?')
        PaperSection.objects.create(paper=completed_paper, title='Intro', is_generated=True)
        QuizAttempt.objects.create(paper=completed_paper, percentage=84, correct_answers=21, total_questions=25, completed_at='2026-01-15T12:00:00Z')
        QuizAttempt.objects.create(paper=completed_paper, percentage=88, correct_answers=22, total_questions=25, completed_at='2026-01-18T12:00:00Z')

        in_progress_paper = Paper.objects.create(owner=user, title='Needs Work', pdf_file='papers/inprogress.pdf')
        AIAnalysis.objects.create(paper=in_progress_paper, beginner_explanation='Only beginner')

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2')
        self.assertContains(response, '1')
        self.assertContains(response, '88%')
        self.assertContains(response, '1')
        self.assertContains(response, 'Continue Learning')

    def test_dashboard_excludes_completed_papers_from_continue_learning_and_limits_recent_papers(self):
        user = User.objects.create_user(username='limituser', email='limituser@example.com', password='Secret123')

        completed_paper = Paper.objects.create(owner=user, title='Completed Paper', pdf_file='papers/completed.pdf')
        AIAnalysis.objects.create(
            paper=completed_paper,
            beginner_explanation='A',
            technical_explanation='B',
            revision_notes='C',
        )
        Glossary.objects.create(paper=completed_paper, term='Model', explanation='Definition')
        Flashcard.objects.create(paper=completed_paper, question='Q?', answer='A')
        QuizQuestion.objects.create(
            paper=completed_paper,
            question='Why?',
            option_a='A',
            option_b='B',
            option_c='C',
            option_d='D',
            correct_answer='A',
        )
        VivaQuestion.objects.create(paper=completed_paper, question='Explain it?')
        PaperSection.objects.create(paper=completed_paper, title='Intro', is_generated=True)

        for index in range(1, 6):
            paper = Paper.objects.create(owner=user, title=f'In Progress {index}', pdf_file=f'papers/inprogress-{index}.pdf')
            AIAnalysis.objects.create(paper=paper, beginner_explanation=f'Intro {index}')

        dashboard = get_dashboard_data(user)

        self.assertEqual(dashboard['papers_in_progress'], 5)
        self.assertEqual(len(dashboard['continue_learning']), 4)
        self.assertEqual(len(dashboard['recent_papers']), 4)
        self.assertIn(completed_paper.title, [item['title'] for item in dashboard['completed_papers']])
        self.assertNotIn(completed_paper.title, [item['title'] for item in dashboard['continue_learning']])

    def test_paper_must_have_all_modules_to_be_marked_complete_even_if_learning_progress_is_true(self):
        user = User.objects.create_user(username='progressuser', email='progressuser@example.com', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Missing Section Learning', pdf_file='papers/missing-section.pdf')
        AIAnalysis.objects.create(
            paper=paper,
            beginner_explanation='A',
            technical_explanation='B',
            revision_notes='C',
        )
        Glossary.objects.create(paper=paper, term='Model', explanation='Definition')
        Flashcard.objects.create(paper=paper, question='Q?', answer='A')
        QuizQuestion.objects.create(
            paper=paper,
            question='Why?',
            option_a='A',
            option_b='B',
            option_c='C',
            option_d='D',
            correct_answer='A',
        )
        VivaQuestion.objects.create(paper=paper, question='Explain it?')
        LearningProgress.objects.create(
            paper=paper,
            beginner_completed=True,
            technical_completed=True,
            glossary_completed=True,
            flashcards_completed=True,
            quiz_completed=True,
            viva_completed=True,
            notes_completed=True,
        )

        self.assertFalse(is_paper_completed(paper))

        dashboard = get_dashboard_data(user)
        self.assertEqual(dashboard['papers_in_progress'], 1)
        self.assertIn(paper.title, [item['title'] for item in dashboard['continue_learning']])
        self.assertNotIn(paper.title, [item['title'] for item in dashboard['completed_papers']])

    def test_my_papers_view_lists_all_uploaded_papers(self):
        user = User.objects.create_user(username='allpapers', email='allpapers@example.com', password='Secret123')
        for index in range(1, 6):
            Paper.objects.create(owner=user, title=f'Paper {index}', pdf_file=f'papers/paper-{index}.pdf')

        self.client.force_login(user)
        response = self.client.get(reverse('my_papers'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Paper 1')
        self.assertContains(response, 'Paper 5')
        self.assertContains(response, 'Upload Paper')

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'Mismatch User',
                'username': 'mismatch',
                'email': 'mismatch@example.com',
                'password1': 'StrongPass123',
                'password2': 'DifferentPass123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The two password fields didn’t match')

    def test_logout_redirects_to_login_page(self):
        self.client.force_login(User.objects.create_user(username='logoutuser', password='Secret123'))
        response = self.client.post(reverse('logout'), follow=True)

        self.assertRedirects(response, reverse('login'))
        self.assertContains(response, 'You have been logged out')

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_login_accepts_email_as_identifier(self):
        user = User.objects.create_user(username='emailuser', email='emailuser@example.com', password='Secret123')
        response = self.client.post(
            reverse('login'),
            {'username': 'emailuser@example.com', 'password': 'Secret123'},
            follow=True,
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_home_redirects_authenticated_users_to_dashboard_and_shows_landing_page_for_guests(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Understand Research Papers Smarter with AI')

        user = User.objects.create_user(username='homeuser', email='homeuser@example.com', password='Secret123')
        self.client.force_login(user)
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_change_password_requires_login(self):
        response = self.client.get(reverse('change_password'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_authenticated_user_can_change_password_and_stay_logged_in(self):
        user = User.objects.create_user(username='passuser', email='passuser@example.com', password='OldSecret123')
        self.client.force_login(user)

        response = self.client.post(
            reverse('change_password'),
            {
                'old_password': 'OldSecret123',
                'new_password1': 'NewStrong123',
                'new_password2': 'NewStrong123',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewStrong123'))
        self.assertContains(response, 'Password changed successfully')


class LandingFlowTests(TestCase):
    def test_landing_page_navbar_is_present_and_visible(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'navbar')
        self.assertContains(response, 'fixed-top')
        self.assertContains(response, 'Features')
        self.assertContains(response, 'How It Works')
        self.assertContains(response, 'Pricing')

    def test_anonymous_landing_premium_button_uses_login_next(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'accounts/login')
        self.assertContains(response, 'next=/subscriptions/pricing/')

    def test_authenticated_landing_premium_button_redirects_to_pricing(self):
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        user = User.objects.create_user(username='landingauth', password='Secret123')
        request = RequestFactory().get('/')
        request.user = user
        html = render_to_string('landing.html', {}, request=request)
        self.assertIn('href="/subscriptions/pricing/"', html)
        self.assertNotIn('accounts/login/?next', html)


class LoginNextTests(TestCase):
    def test_login_with_next_redirects_safely_to_pricing(self):
        User.objects.create_user(username='nextuser', password='Secret123')
        response = self.client.post(
            reverse('login'),
            {'username': 'nextuser', 'password': 'Secret123', 'next': '/subscriptions/pricing/'},
        )
        self.assertRedirects(response, '/subscriptions/pricing/')

    def test_login_rejects_unsafe_external_next(self):
        User.objects.create_user(username='unsafenext', password='Secret123')
        response = self.client.post(
            reverse('login'),
            {'username': 'unsafenext', 'password': 'Secret123', 'next': 'https://evil.example.com'},
        )
        self.assertRedirects(response, reverse('dashboard'))
