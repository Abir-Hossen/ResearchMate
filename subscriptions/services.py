from django.utils import timezone

from .models import UserSubscription


def get_active_subscription(user):
    now = timezone.now()
    return user.subscriptions.filter(status='ACTIVE', end_date__gte=now).order_by('-end_date').first()


def user_has_premium_access(user):
    subscription = user.subscriptions.filter(status='ACTIVE').order_by('-end_date').first()
    if subscription is None:
        return False
    if subscription.end_date is None:
        return False
    if timezone.now() > subscription.end_date:
        subscription.status = 'EXPIRED'
        subscription.save(update_fields=['status'])
        return False
    return True


def get_current_subscription_status(user):
    subscription = get_active_subscription(user)
    if subscription is None:
        return {
            'has_premium': False,
            'plan': None,
            'status': None,
            'start_date': None,
            'end_date': None,
            'days_remaining': None,
        }
    days_remaining = (subscription.end_date - timezone.now()).days
    return {
        'has_premium': True,
        'plan': subscription.plan,
        'status': subscription.status,
        'start_date': subscription.start_date,
        'end_date': subscription.end_date,
        'days_remaining': max(days_remaining, 0),
    }


def expire_outdated_subscriptions():
    now = timezone.now()
    outdated = UserSubscription.objects.filter(status='ACTIVE', end_date__lt=now)
    count = outdated.update(status='EXPIRED')
    return count


def activate_subscription(user, plan):
    now = timezone.now()
    UserSubscription.objects.filter(user=user, status='ACTIVE').update(status='EXPIRED')
    subscription = UserSubscription.objects.create(
        user=user,
        plan=plan,
        status='ACTIVE',
        start_date=now,
        end_date=now + timezone.timedelta(days=plan.duration_days),
    )
    return subscription
