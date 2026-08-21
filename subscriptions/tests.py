from datetime import timedelta

import requests
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from papers.models import Paper
from .models import PaymentTransaction, SubscriptionPlan, UserSubscription
from .services import (
    activate_subscription,
    create_payment_transaction,
    expire_outdated_subscriptions,
    get_active_subscription,
    get_current_subscription_status,
    mark_transaction_cancelled,
    mark_transaction_failed,
    mark_transaction_pending,
    mark_transaction_success_for_testing,
    user_has_premium_access,
)
from .sslcommerz_service import SSLCommerzError, initiate_sslcommerz_payment


def make_gateway_response(json_data, text='', status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json_data
    response.text = text
    response.raise_for_status.return_value = None
    return response


class SubscriptionPlanTests(TestCase):
    def test_create_premium_weekly_plan(self):
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-test-unique',
            description='Weekly premium access.',
            price=Decimal('9.99'),
            duration_days=7,
            is_active=True,
        )
        self.assertEqual(plan.slug, 'premium-weekly-test-unique')
        self.assertEqual(plan.duration_days, 7)
        self.assertEqual(plan.price, Decimal('9.99'))
        self.assertTrue(plan.is_active)

    def test_create_premium_monthly_plan(self):
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-test-unique',
            description='Monthly premium access.',
            price=Decimal('29.99'),
            duration_days=30,
            is_active=True,
        )
        self.assertEqual(plan.slug, 'premium-monthly-test-unique')
        self.assertEqual(plan.duration_days, 30)
        self.assertTrue(plan.is_active)

    def test_initial_plans_are_created(self):
        plans = SubscriptionPlan.objects.all()
        self.assertEqual(plans.count(), 2)
        slugs = {plan.slug for plan in plans}
        self.assertIn('premium-weekly', slugs)
        self.assertIn('premium-monthly', slugs)


class UserSubscriptionTests(TestCase):
    def test_create_user_subscription(self):
        user = User.objects.create_user(username='subuser', email='sub@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-sub-unique',
            description='Test weekly plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        subscription = UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now,
            end_date=now + timedelta(days=7),
        )
        self.assertEqual(subscription.user, user)
        self.assertEqual(subscription.plan, plan)
        self.assertEqual(subscription.status, 'ACTIVE')
        self.assertIsNotNone(subscription.start_date)

    def test_default_status_is_pending(self):
        user = User.objects.create_user(username='pendinguser', email='pending@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-pending-unique',
            description='Test monthly plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        subscription = UserSubscription.objects.create(user=user, plan=plan)
        self.assertEqual(subscription.status, 'PENDING')


class PremiumAccessTests(TestCase):
    def test_user_with_active_subscription_has_premium_access(self):
        user = User.objects.create_user(username='premiumactive', email='premiumactive@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-active-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now,
            end_date=now + timedelta(days=7),
        )
        self.assertTrue(user_has_premium_access(user))

    def test_user_with_expired_subscription_has_no_premium_access(self):
        user = User.objects.create_user(username='premiumexpired', email='premiumexpired@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-expired-unique',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now - timedelta(days=40),
            end_date=now - timedelta(days=10),
        )
        self.assertFalse(user_has_premium_access(user))

    def test_user_with_no_subscription_has_no_premium_access(self):
        user = User.objects.create_user(username='nosub', email='nosub@example.com', password='Secret123')
        self.assertFalse(user_has_premium_access(user))

    def test_basic_user_with_no_subscription(self):
        user = User.objects.create_user(username='basicuser', email='basic@example.com', password='Secret123')
        self.assertFalse(user_has_premium_access(user))
        status = get_current_subscription_status(user)
        self.assertFalse(status['has_premium'])
        self.assertIsNone(status['plan'])

    def test_automatic_expiration_after_end_date(self):
        user = User.objects.create_user(username='autoexpire', email='autoexpire@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-auto-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        subscription = UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=3),
        )
        self.assertFalse(user_has_premium_access(user))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, 'EXPIRED')


class ActivateSubscriptionTests(TestCase):
    def test_activate_subscription_sets_dates(self):
        user = User.objects.create_user(username='activateuser', email='activate@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-activate-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        subscription = activate_subscription(user, plan)
        self.assertEqual(subscription.status, 'ACTIVE')
        self.assertIsNotNone(subscription.start_date)
        self.assertEqual(subscription.end_date.date(), subscription.start_date.date() + timedelta(days=7))

    def test_activate_monthly_subscription(self):
        user = User.objects.create_user(username='monthlyactivate', email='monthly@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-activate-unique',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        subscription = activate_subscription(user, plan)
        self.assertEqual(subscription.status, 'ACTIVE')
        self.assertEqual(subscription.end_date.date(), subscription.start_date.date() + timedelta(days=30))

    def test_activate_subscription_expires_previous_active(self):
        user = User.objects.create_user(username='expireprev', email='expireprev@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-expire-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        old_subscription = UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=timezone.now() - timedelta(days=5),
            end_date=timezone.now() + timedelta(days=2),
        )
        new_plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-expire-unique',
            description='Test plan 2.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        activate_subscription(user, new_plan)
        old_subscription.refresh_from_db()
        self.assertEqual(old_subscription.status, 'EXPIRED')

    def test_activate_subscription_grants_premium_access(self):
        user = User.objects.create_user(username='grantpremium', email='grantpremium@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-grant-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        activate_subscription(user, plan)
        self.assertTrue(user_has_premium_access(user))


class ExpireOutdatedSubscriptionsTests(TestCase):
    def test_expire_outdated_subscriptions(self):
        user = User.objects.create_user(username='expirebatch', email='expirebatch@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-batch-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=3),
        )
        count = expire_outdated_subscriptions()
        self.assertEqual(count, 1)
        self.assertFalse(UserSubscription.objects.filter(status='ACTIVE').exists())

    def test_does_not_expire_active_subscriptions(self):
        user = User.objects.create_user(username='dontexpire', email='dontexpire@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-dontexpire-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now,
            end_date=now + timedelta(days=7),
        )
        count = expire_outdated_subscriptions()
        self.assertEqual(count, 0)
        self.assertTrue(UserSubscription.objects.filter(status='ACTIVE').exists())


class GetActiveSubscriptionTests(TestCase):
    def test_returns_active_subscription(self):
        user = User.objects.create_user(username='getactive', email='getactive@example.com', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-getactive-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now,
            end_date=now + timedelta(days=7),
        )
        subscription = get_active_subscription(user)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.status, 'ACTIVE')

    def test_returns_none_when_no_active_subscription(self):
        user = User.objects.create_user(username='getnone', email='getnone@example.com', password='Secret123')
        self.assertIsNone(get_active_subscription(user))


class PremiumFeatureAccessControlTests(TestCase):
    def test_basic_user_cannot_access_technical_explanation(self):
        user = User.objects.create_user(username='basictech', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Tech Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_basic_user_cannot_access_section_learning(self):
        user = User.objects.create_user(username='basicsect', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Section Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_sections', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fsections%2F')

    def test_basic_user_cannot_access_glossary(self):
        user = User.objects.create_user(username='basicgloss', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Glossary Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_glossary', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fglossary%2F')

    def test_basic_user_cannot_access_flashcards(self):
        user = User.objects.create_user(username='basicflash', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Flashcard Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_flashcards', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fflashcards%2F')

    def test_basic_user_cannot_access_quiz(self):
        user = User.objects.create_user(username='basicquiz', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Quiz Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_quiz', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fquiz%2F')

    def test_basic_user_cannot_access_viva(self):
        user = User.objects.create_user(username='basicviva', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Viva Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_viva', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fviva%2F')

    def test_basic_user_cannot_access_notes(self):
        user = User.objects.create_user(username='basicnotes', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Notes Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_notes', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fnotes%2F')

    def test_basic_user_can_access_beginner_explanation(self):
        user = User.objects.create_user(username='basicbeginner', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Beginner Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_beginner', args=[paper.pk]))
        self.assertEqual(response.status_code, 200)

    def test_basic_user_post_generation_blocked_for_technical(self):
        user = User.objects.create_user(username='basicposttech', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Post Tech Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.post(reverse('paper_technical', args=[paper.pk]), follow=True)
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_basic_user_post_generation_blocked_for_quiz(self):
        user = User.objects.create_user(username='basicpostquiz', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Basic Post Quiz Paper', pdf_file='papers/basic.pdf')
        self.client.force_login(user)
        response = self.client.post(reverse('paper_quiz', args=[paper.pk]), {'action': 'generate'}, follow=True)
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Fquiz%2F')

    def test_premium_user_can_access_all_premium_features(self):
        from papers.models import Paper
        user = User.objects.create_user(username='premiumall', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-all-unique',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        activate_subscription(user, plan)
        paper = Paper.objects.create(owner=user, title='Premium All Paper', pdf_file='papers/premium.pdf')

        self.client.force_login(user)
        for url_name in ['paper_technical', 'paper_sections', 'paper_glossary', 'paper_flashcards', 'paper_quiz', 'paper_viva', 'paper_notes']:
            response = self.client.get(reverse(url_name, args=[paper.pk]))
            self.assertEqual(response.status_code, 200, msg=f'Failed for {url_name}')

    def test_expired_user_is_denied_premium_access(self):
        user = User.objects.create_user(username='expiredaccess', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-expired-access',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        now = timezone.now()
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            status='ACTIVE',
            start_date=now - timedelta(days=10),
            end_date=now - timedelta(days=3),
        )
        paper = Paper.objects.create(owner=user, title='Expired Access Paper', pdf_file='papers/expired.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_pending_user_is_denied_premium_access(self):
        user = User.objects.create_user(username='pendingaccess', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-pending-access',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        UserSubscription.objects.create(user=user, plan=plan, status='PENDING')
        paper = Paper.objects.create(owner=user, title='Pending Access Paper', pdf_file='papers/pending.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_cancelled_user_is_denied_premium_access(self):
        user = User.objects.create_user(username='cancelledaccess', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-cancelled-access',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        UserSubscription.objects.create(user=user, plan=plan, status='CANCELLED')
        paper = Paper.objects.create(owner=user, title='Cancelled Access Paper', pdf_file='papers/cancelled.pdf')
        self.client.force_login(user)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_premium_access_does_not_bypass_paper_ownership(self):
        owner = User.objects.create_user(username='ownerpremium', password='Secret123')
        other = User.objects.create_user(username='otherpremium', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-ownership',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        activate_subscription(other, plan)
        paper = Paper.objects.create(owner=owner, title='Ownership Paper', pdf_file='papers/ownership.pdf')
        self.client.force_login(other)
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertEqual(response.status_code, 404)

    def test_pricing_page_loads_plans_from_database(self):
        user = User.objects.create_user(username='pricinguser', password='Secret123')
        self.client.force_login(user)
        response = self.client.get(reverse('subscriptions:pricing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Premium Weekly')
        self.assertContains(response, 'Premium Monthly')

    def test_pricing_page_redirects_unauthenticated_users(self):
        response = self.client.get(reverse('subscriptions:pricing'))
        self.assertRedirects(response, reverse('login') + '?next=%2Fsubscriptions%2Fpricing%2F')


class DashboardSubscriptionStatusTests(TestCase):
    def test_basic_user_sees_basic_plan_status(self):
        user = User.objects.create_user(username='dashboardbasic', password='Secret123')
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Basic Plan')
        self.assertContains(response, 'Upgrade to Premium')

    def test_premium_user_sees_premium_plan_status(self):
        user = User.objects.create_user(username='dashboardpremium', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-dashboard',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        activate_subscription(user, plan)
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Premium Weekly')
        self.assertContains(response, 'ACTIVE')

    def test_premium_user_sees_expiry_information(self):
        user = User.objects.create_user(username='dashboardexpiry', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-dashboard',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        activate_subscription(user, plan)
        self.client.force_login(user)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'days remaining')


class PaymentTransactionModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='payuser', email='pay@example.com', password='Secret123')
        self.plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-paymodel',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
            is_active=True,
        )

    def test_payment_transaction_can_be_created(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertIsNotNone(txn.pk)
        self.assertEqual(txn.user, self.user)
        self.assertEqual(txn.plan, self.plan)

    def test_transaction_id_is_automatically_generated(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertTrue(txn.transaction_id.startswith('RM-'))
        self.assertRegex(txn.transaction_id, r'^RM-\d{8}-[A-Z0-9]{8}$')

    def test_transaction_ids_are_unique(self):
        txn1 = create_payment_transaction(self.user, self.plan)
        txn2 = create_payment_transaction(self.user, self.plan)
        self.assertNotEqual(txn1.transaction_id, txn2.transaction_id)

    def test_default_status_is_initiated(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.INITIATED)

    def test_amount_is_copied_from_plan_price(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.amount, Decimal('9.99'))

    def test_amount_snapshot_independent_of_plan_price_change(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.plan.price = Decimal('99.99')
        self.plan.save()
        txn.refresh_from_db()
        self.assertEqual(txn.amount, Decimal('9.99'))

    def test_currency_defaults_to_bdt(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.currency, 'BDT')

    def test_payment_transaction_belongs_to_correct_user(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.user, self.user)
        self.assertIn(txn, self.user.payment_transactions.all())

    def test_payment_transaction_belongs_to_correct_plan(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.plan, self.plan)
        self.assertIn(txn, self.plan.payment_transactions.all())

    def test_initiated_at_set_on_creation(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertIsNotNone(txn.initiated_at)


class PaymentTransactionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='paysvc', email='paysvc@example.com', password='Secret123')
        self.plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-paysvc',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
            is_active=True,
        )

    def test_create_payment_transaction_creates_correct_transaction(self):
        txn = create_payment_transaction(self.user, self.plan)
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.INITIATED)
        self.assertEqual(txn.amount, Decimal('29.99'))
        self.assertEqual(txn.currency, 'BDT')
        self.assertEqual(txn.payment_gateway, PaymentTransaction.PaymentGateway.SSLCOMMERZ)

    def test_inactive_plan_cannot_be_used(self):
        self.plan.is_active = False
        self.plan.save()
        with self.assertRaises(Exception):
            create_payment_transaction(self.user, self.plan)

    def test_mark_transaction_pending_changes_status(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.PENDING)

    def test_mark_transaction_success_for_testing_sets_success_and_timestamps(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_success_for_testing(txn)
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.SUCCESS)
        self.assertIsNotNone(txn.completed_at)
        self.assertIsNotNone(txn.verified_at)

    def test_success_testing_does_not_activate_premium(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_success_for_testing(txn)
        self.assertFalse(user_has_premium_access(self.user))

    def test_mark_transaction_failed_stores_failure_reason(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_failed(txn, reason='Card declined')
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.FAILED)
        self.assertEqual(txn.failure_reason, 'Card declined')
        self.assertIsNotNone(txn.completed_at)

    def test_failed_payment_does_not_activate_premium(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_failed(txn, reason='Timeout')
        self.assertFalse(user_has_premium_access(self.user))

    def test_mark_transaction_cancelled_works(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_cancelled(txn)
        self.assertEqual(txn.status, PaymentTransaction.PaymentStatus.CANCELLED)
        self.assertIsNotNone(txn.completed_at)

    def test_cancelled_payment_does_not_activate_premium(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_cancelled(txn)
        self.assertFalse(user_has_premium_access(self.user))


class PaymentStatusTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='paytrans', email='paytrans@example.com', password='Secret123')
        self.plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-paytrans',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
            is_active=True,
        )

    def test_invalid_status_transition_rejected(self):
        txn = create_payment_transaction(self.user, self.plan)
        with self.assertRaises(Exception):
            mark_transaction_success_for_testing(txn)

    def test_success_cannot_move_back_to_pending(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_success_for_testing(txn)
        with self.assertRaises(Exception):
            mark_transaction_pending(txn)

    def test_failed_cannot_be_marked_success_directly(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_pending(txn)
        txn = mark_transaction_failed(txn, reason='Error')
        with self.assertRaises(Exception):
            mark_transaction_success_for_testing(txn)

    def test_cancelled_cannot_be_marked_success_directly(self):
        txn = create_payment_transaction(self.user, self.plan)
        txn = mark_transaction_cancelled(txn)
        with self.assertRaises(Exception):
            mark_transaction_success_for_testing(txn)

    def test_initiated_can_move_to_pending_or_cancelled(self):
        txn = create_payment_transaction(self.user, self.plan)
        pending = mark_transaction_pending(txn)
        self.assertEqual(pending.status, PaymentTransaction.PaymentStatus.PENDING)
        txn2 = create_payment_transaction(self.user, self.plan)
        cancelled = mark_transaction_cancelled(txn2)
        self.assertEqual(cancelled.status, PaymentTransaction.PaymentStatus.CANCELLED)


class PaymentRegressionTests(TestCase):
    def test_existing_basic_user_remains_basic(self):
        user = User.objects.create_user(username='regbasic', password='Secret123')
        self.assertFalse(user_has_premium_access(user))

    def test_existing_premium_user_remains_premium(self):
        user = User.objects.create_user(username='regpremium', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-regpremium',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        activate_subscription(user, plan)
        self.assertTrue(user_has_premium_access(user))

    def test_user_has_premium_access_behavior_unchanged(self):
        basic = User.objects.create_user(username='regaccessbasic', password='Secret123')
        self.assertFalse(user_has_premium_access(basic))
        premium = User.objects.create_user(username='regaccesspremium', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-regaccess',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        activate_subscription(premium, plan)
        self.assertTrue(user_has_premium_access(premium))

    def test_activate_subscription_behavior_unchanged(self):
        user = User.objects.create_user(username='regactivate', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-regactivate',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        subscription = activate_subscription(user, plan)
        self.assertEqual(subscription.status, 'ACTIVE')
        self.assertTrue(user_has_premium_access(user))


class SSLCommerzServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ssluser', email='ssl@example.com', password='Secret123')
        self.plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-ssl',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
            is_active=True,
        )

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_correct_transaction_data_is_sent(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
            'sessionkey': 'SK123',
        })
        transaction = create_payment_transaction(self.user, self.plan)
        gateway_url = initiate_sslcommerz_payment(transaction)
        self.assertEqual(gateway_url, 'https://sandbox.sslcommerz.com/pay/abc')

        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], 'https://sandbox.sslcommerz.com/gwprocess/v4/api.php')
        payload = kwargs['data']
        self.assertEqual(payload['total_amount'], str(transaction.amount))
        self.assertEqual(payload['currency'], 'BDT')
        self.assertEqual(payload['tran_id'], transaction.transaction_id)
        self.assertEqual(payload['store_id'], settings.SSLCOMMERZ_STORE_ID)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_amount_uses_payment_snapshot(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
        })
        transaction = create_payment_transaction(self.user, self.plan)
        self.plan.price = Decimal('99.99')
        self.plan.save()
        initiate_sslcommerz_payment(transaction)
        payload = mock_post.call_args.kwargs['data']
        self.assertEqual(payload['total_amount'], '9.99')

    def test_sandbox_configuration_is_used(self):
        with self.settings(SSLCOMMERZ_SANDBOX=False):
            from subscriptions.sslcommerz_service import get_api_endpoint
            self.assertEqual(get_api_endpoint(), 'https://securepay.sslcommerz.com/gwprocess/v4/api.php')
        with self.settings(SSLCOMMERZ_SANDBOX=True):
            from subscriptions.sslcommerz_service import get_api_endpoint
            self.assertEqual(get_api_endpoint(), 'https://sandbox.sslcommerz.com/gwprocess/v4/api.php')

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_successful_initiation_returns_gateway_url(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/xyz',
        })
        transaction = create_payment_transaction(self.user, self.plan)
        url = initiate_sslcommerz_payment(transaction)
        self.assertEqual(url, 'https://sandbox.sslcommerz.com/pay/xyz')
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.INITIATED)
        self.assertEqual(transaction.gateway_transaction_id, None)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_sessionkey_stored_as_gateway_transaction_id(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/xyz',
            'sessionkey': 'SESSION-KEY-1',
        })
        transaction = create_payment_transaction(self.user, self.plan)
        initiate_sslcommerz_payment(transaction)
        transaction.refresh_from_db()
        self.assertEqual(transaction.gateway_transaction_id, 'SESSION-KEY-1')

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_invalid_gateway_response_handled(self, mock_post):
        bad = make_gateway_response({})
        bad.json.side_effect = ValueError('not json')
        mock_post.return_value = bad
        transaction = create_payment_transaction(self.user, self.plan)
        with self.assertRaises(SSLCommerzError):
            initiate_sslcommerz_payment(transaction)
        transaction.refresh_from_db()
        self.assertIn('invalid_gateway_response', transaction.gateway_response)
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.INITIATED)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_missing_gateway_url_handled(self, mock_post):
        mock_post.return_value = make_gateway_response({'status': 'SUCCESS'})
        transaction = create_payment_transaction(self.user, self.plan)
        with self.assertRaises(SSLCommerzError):
            initiate_sslcommerz_payment(transaction)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_failed_gateway_status_handled(self, mock_post):
        mock_post.return_value = make_gateway_response({'status': 'FAILED', 'failReason': 'Declined'})
        transaction = create_payment_transaction(self.user, self.plan)
        with self.assertRaises(SSLCommerzError):
            initiate_sslcommerz_payment(transaction)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_network_error_handled(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError('boom')
        transaction = create_payment_transaction(self.user, self.plan)
        with self.assertRaises(SSLCommerzError):
            initiate_sslcommerz_payment(transaction)
        transaction.refresh_from_db()
        self.assertIn('gateway_connection_error', transaction.gateway_response)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_sensitive_credentials_not_exposed(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
        })
        with self.settings(SSLCOMMERZ_STORE_PASSWORD='SUPER_SECRET_PASSWORD'):
            transaction = create_payment_transaction(self.user, self.plan)
            initiate_sslcommerz_payment(transaction)
        transaction.refresh_from_db()
        self.assertNotIn('SUPER_SECRET_PASSWORD', transaction.gateway_response)

    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_ineligible_transaction_rejected(self, mock_post):
        transaction = create_payment_transaction(self.user, self.plan)
        mark_transaction_pending(transaction)
        with self.assertRaises(SSLCommerzError):
            initiate_sslcommerz_payment(transaction)
        mock_post.assert_not_called()


class CheckoutViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='checkoutuser', email='checkout@example.com', password='Secret123')
        self.plan = SubscriptionPlan.objects.get(slug='premium-weekly')

    def test_authentication_required(self):
        response = self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_get_does_not_initiate_payment(self):
        self.client.login(username='checkoutuser', password='Secret123')
        response = self.client.get(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    @override_settings(SSLCOMMERZ_STORE_ID='test_store', SSLCOMMERZ_STORE_PASSWORD='test_pass')
    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_post_creates_payment_transaction(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
        })
        self.client.login(username='checkoutuser', password='Secret123')
        response = self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PaymentTransaction.objects.count(), 1)
        transaction = PaymentTransaction.objects.first()
        self.assertEqual(transaction.user, self.user)
        self.assertEqual(transaction.plan, self.plan)
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.PENDING)
        self.assertEqual(response['Location'], 'https://sandbox.sslcommerz.com/pay/abc')

    def test_inactive_plan_rejected(self):
        self.plan.is_active = False
        self.plan.save()
        self.client.login(username='checkoutuser', password='Secret123')
        response = self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_nonexistent_plan_rejected(self):
        self.client.login(username='checkoutuser', password='Secret123')
        response = self.client.post(reverse('subscriptions:checkout', args=['not-a-real-plan']))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    @override_settings(SSLCOMMERZ_STORE_ID='test_store', SSLCOMMERZ_STORE_PASSWORD='test_pass')
    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_failed_gateway_initiation_marks_failed(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError('boom')
        self.client.login(username='checkoutuser', password='Secret123')
        response = self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('subscriptions:pricing'))
        transaction = PaymentTransaction.objects.first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.FAILED)
        self.assertIsNotNone(transaction.failure_reason)

    @override_settings(SSLCOMMERZ_STORE_ID='test_store', SSLCOMMERZ_STORE_PASSWORD='test_pass')
    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_payment_initiation_does_not_activate_premium(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
        })
        self.client.login(username='checkoutuser', password='Secret123')
        self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertFalse(user_has_premium_access(self.user))

    @override_settings(SSLCOMMERZ_STORE_ID='test_store', SSLCOMMERZ_STORE_PASSWORD='test_pass')
    @patch('subscriptions.sslcommerz_service.requests.post')
    def test_existing_premium_user_subscription_not_modified(self, mock_post):
        mock_post.return_value = make_gateway_response({
            'status': 'SUCCESS',
            'GatewayPageURL': 'https://sandbox.sslcommerz.com/pay/abc',
        })
        activate_subscription(self.user, self.plan)
        self.assertTrue(user_has_premium_access(self.user))
        self.client.login(username='checkoutuser', password='Secret123')
        self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(UserSubscription.objects.filter(user=self.user, status='ACTIVE').count(), 1)
        self.assertTrue(user_has_premium_access(self.user))
        transaction = PaymentTransaction.objects.first()
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.PENDING)


class PaymentPhaseRegressionTests(TestCase):
    def test_user_has_premium_access_unchanged(self):
        basic = User.objects.create_user(username='phaseregbasic', password='Secret123')
        self.assertFalse(user_has_premium_access(basic))
        premium = User.objects.create_user(username='phaseregpremium', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Monthly',
            slug='premium-monthly-phasereg',
            description='Test plan.',
            price=Decimal('29.99'),
            duration_days=30,
        )
        activate_subscription(premium, plan)
        self.assertTrue(user_has_premium_access(premium))

    def test_premium_required_blocks_basic_user(self):
        user = User.objects.create_user(username='phaseregblocked', password='Secret123')
        paper = Paper.objects.create(owner=user, title='Regression Paper', pdf_file='papers/reg.pdf')
        self.client.login(username='phaseregblocked', password='Secret123')
        response = self.client.get(reverse('paper_technical', args=[paper.pk]))
        self.assertRedirects(response, reverse('subscriptions:pricing') + '?next=%2Fpapers%2F1%2Ftechnical%2F')

    def test_basic_user_pricing_shows_no_payment_transaction(self):
        user = User.objects.create_user(username='phaseregbasic2', password='Secret123')
        self.client.login(username='phaseregbasic2', password='Secret123')
        response = self.client.get(reverse('subscriptions:pricing'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PaymentTransaction.objects.count(), 0)


class PlanConfigurationTests(TestCase):
    def test_weekly_plan_price_finalized(self):
        weekly = SubscriptionPlan.objects.get(slug='premium-weekly')
        self.assertEqual(weekly.price, Decimal('99.00'))
        self.assertEqual(weekly.duration_days, 7)
        self.assertTrue(weekly.is_active)

    def test_monthly_plan_price_finalized(self):
        monthly = SubscriptionPlan.objects.get(slug='premium-monthly')
        self.assertEqual(monthly.price, Decimal('299.00'))
        self.assertEqual(monthly.duration_days, 30)
        self.assertTrue(monthly.is_active)

    def test_no_duplicate_plans_created(self):
        self.assertEqual(SubscriptionPlan.objects.filter(slug='premium-weekly').count(), 1)
        self.assertEqual(SubscriptionPlan.objects.filter(slug='premium-monthly').count(), 1)
        self.assertEqual(SubscriptionPlan.objects.count(), 2)

    def test_historical_transaction_amount_not_changed_by_plan_price_update(self):
        user = User.objects.create_user(username='snapshotuser', password='Secret123')
        plan = SubscriptionPlan.objects.create(
            name='Premium Weekly',
            slug='premium-weekly-snapshot',
            description='Test plan.',
            price=Decimal('9.99'),
            duration_days=7,
        )
        transaction = create_payment_transaction(user, plan)
        self.assertEqual(transaction.amount, Decimal('9.99'))

        plan.price = Decimal('999.00')
        plan.save()

        transaction.refresh_from_db()
        self.assertEqual(transaction.amount, Decimal('9.99'))


class PricingPageDisplayTests(TestCase):
    def test_pricing_page_displays_database_prices(self):
        user = User.objects.create_user(username='pricedisplay', password='Secret123')
        self.client.login(username='pricedisplay', password='Secret123')
        response = self.client.get(reverse('subscriptions:pricing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '৳99.00')
        self.assertContains(response, '৳299.00')

    def test_pricing_page_displays_database_durations(self):
        user = User.objects.create_user(username='durationdisplay', password='Secret123')
        self.client.login(username='durationdisplay', password='Secret123')
        response = self.client.get(reverse('subscriptions:pricing'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '7-day access')
        self.assertContains(response, '30-day access')


class CheckoutMissingCredentialsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='missingcred', password='Secret123')
        self.plan = SubscriptionPlan.objects.get(slug='premium-weekly')

    @override_settings(SSLCOMMERZ_STORE_ID='', SSLCOMMERZ_STORE_PASSWORD='EXPOSED_SECRET_XYZ')
    def test_checkout_without_credentials_fails_safely(self):
        self.client.login(username='missingcred', password='Secret123')
        response = self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('subscriptions:pricing'))

        transaction = PaymentTransaction.objects.first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.status, PaymentTransaction.PaymentStatus.FAILED)
        self.assertIn('Payment service is currently unavailable', transaction.failure_reason)

    @override_settings(SSLCOMMERZ_STORE_ID='', SSLCOMMERZ_STORE_PASSWORD='EXPOSED_SECRET_XYZ')
    def test_missing_credentials_do_not_expose_secrets(self):
        self.client.login(username='missingcred', password='Secret123')
        self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        transaction = PaymentTransaction.objects.first()
        self.assertNotIn('EXPOSED_SECRET_XYZ', transaction.gateway_response)

    def test_missing_credentials_do_not_activate_premium(self):
        with self.settings(SSLCOMMERZ_STORE_ID='', SSLCOMMERZ_STORE_PASSWORD=''):
            self.client.login(username='missingcred', password='Secret123')
            self.client.post(reverse('subscriptions:checkout', args=['premium-weekly']))
        self.assertFalse(user_has_premium_access(self.user))

