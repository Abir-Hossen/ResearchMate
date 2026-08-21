from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import PaymentTransaction, UserSubscription


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


def create_payment_transaction(user, plan):
    if not plan.is_active:
        raise ValidationError('Cannot create a payment transaction for an inactive subscription plan.')

    transaction = PaymentTransaction.objects.create(
        user=user,
        plan=plan,
        amount=plan.price,
        currency='BDT',
        status=PaymentTransaction.PaymentStatus.INITIATED,
        payment_gateway=PaymentTransaction.PaymentGateway.SSLCOMMERZ,
    )
    return transaction


def _validate_transition(transaction, new_status):
    if transaction.status == new_status:
        raise ValidationError(f'Transaction is already in status {new_status}.')
    if not transaction.can_transition_to(new_status):
        raise ValidationError(
            f'Invalid payment status transition from {transaction.status} to {new_status}.'
        )


def mark_transaction_pending(transaction):
    _validate_transition(transaction, PaymentTransaction.PaymentStatus.PENDING)
    transaction.status = PaymentTransaction.PaymentStatus.PENDING
    transaction.save(update_fields=['status', 'updated_at'])
    return transaction


def mark_transaction_success_for_testing(transaction):
    _validate_transition(transaction, PaymentTransaction.PaymentStatus.SUCCESS)
    now = timezone.now()
    transaction.status = PaymentTransaction.PaymentStatus.SUCCESS
    transaction.completed_at = now
    transaction.verified_at = now
    transaction.save(update_fields=['status', 'completed_at', 'verified_at', 'updated_at'])
    return transaction


def mark_transaction_failed(transaction, reason=None):
    _validate_transition(transaction, PaymentTransaction.PaymentStatus.FAILED)
    transaction.status = PaymentTransaction.PaymentStatus.FAILED
    transaction.completed_at = timezone.now()
    if reason is not None:
        transaction.failure_reason = reason
    transaction.save(update_fields=['status', 'completed_at', 'failure_reason', 'updated_at'])
    return transaction


def mark_transaction_cancelled(transaction):
    _validate_transition(transaction, PaymentTransaction.PaymentStatus.CANCELLED)
    transaction.status = PaymentTransaction.PaymentStatus.CANCELLED
    transaction.completed_at = timezone.now()
    transaction.save(update_fields=['status', 'completed_at', 'updated_at'])
    return transaction
