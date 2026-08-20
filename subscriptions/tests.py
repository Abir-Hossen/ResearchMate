from datetime import timedelta

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from papers.models import Paper
from .models import SubscriptionPlan, UserSubscription
from .services import activate_subscription, expire_outdated_subscriptions, get_active_subscription, get_current_subscription_status, user_has_premium_access


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

