from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from subscriptions.models import SubscriptionPlan


class SubscriptionPlanValidationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='planadmin',
            password='Secret123',
            is_staff=True,
        )
        self.client.force_login(self.staff)

    def test_plan_create_rejects_non_positive_values_and_invalid_slug(self):
        plans_before = SubscriptionPlan.objects.count()
        response = self.client.post(
            reverse('admin_panel:plan_create'),
            {
                'name': 'Invalid Plan',
                'slug': 'invalid_slug',
                'description': '',
                'price': '0',
                'duration_days': '-1',
            },
        )

        self.assertRedirects(response, reverse('admin_panel:plan_create'))
        self.assertEqual(SubscriptionPlan.objects.count(), plans_before)

    def test_plan_edit_rejects_non_positive_values(self):
        plan = SubscriptionPlan.objects.create(
            name='Existing Plan',
            slug='existing-plan',
            price=Decimal('9.99'),
            duration_days=7,
        )

        response = self.client.post(
            reverse('admin_panel:plan_edit', args=[plan.pk]),
            {
                'name': 'Updated Plan',
                'slug': 'updated-plan',
                'description': '',
                'price': '-1',
                'duration_days': '0',
            },
        )

        self.assertRedirects(response, reverse('admin_panel:plan_edit', args=[plan.pk]))
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'Existing Plan')
        self.assertEqual(plan.price, Decimal('9.99'))
        self.assertEqual(plan.duration_days, 7)

    def test_plan_create_accepts_valid_values(self):
        response = self.client.post(
            reverse('admin_panel:plan_create'),
            {
                'name': 'Valid Plan',
                'slug': 'valid-plan',
                'description': 'A valid subscription plan.',
                'price': '19.99',
                'duration_days': '30',
                'is_active': 'on',
            },
        )

        self.assertRedirects(response, reverse('admin_panel:plan_list'))
        plan = SubscriptionPlan.objects.get(slug='valid-plan')
        self.assertEqual(plan.price, Decimal('19.99'))
        self.assertEqual(plan.duration_days, 30)