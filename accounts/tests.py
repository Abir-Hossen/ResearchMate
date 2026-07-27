from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User


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
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent Activity')
        self.assertContains(response, 'Quick Actions')
        self.assertContains(response, 'Getting Started')

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

    def test_home_redirects_guests_to_login_and_users_to_dashboard(self):
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('login'))

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
