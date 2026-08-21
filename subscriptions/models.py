import uuid

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class PaymentTransaction(models.Model):
    class PaymentStatus(models.TextChoices):
        INITIATED = 'INITIATED', 'Initiated'
        PENDING = 'PENDING', 'Pending'
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentGateway(models.TextChoices):
        SSLCOMMERZ = 'SSLCOMMERZ', 'SSLCommerz'
        MANUAL = 'MANUAL', 'Manual'
        TEST = 'TEST', 'Test'

    ALLOWED_TRANSITIONS = {
        PaymentStatus.INITIATED: {PaymentStatus.PENDING, PaymentStatus.CANCELLED, PaymentStatus.FAILED},
        PaymentStatus.PENDING: {PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.CANCELLED},
        PaymentStatus.SUCCESS: set(),
        PaymentStatus.FAILED: set(),
        PaymentStatus.CANCELLED: set(),
    }

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_transactions')
    plan = models.ForeignKey('subscriptions.SubscriptionPlan', on_delete=models.PROTECT, related_name='payment_transactions')

    transaction_id = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.INITIATED)

    payment_gateway = models.CharField(max_length=20, choices=PaymentGateway.choices, default=PaymentGateway.SSLCOMMERZ)

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='BDT')

    gateway_transaction_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    gateway_response = models.TextField(blank=True, default='')
    failure_reason = models.TextField(blank=True, default='')

    initiated_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'payment_gateway']),
        ]

    def __str__(self):
        return f'{self.transaction_id} - {self.user.username} - {self.plan.name} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()
        if self.initiated_at is None:
            self.initiated_at = timezone.now()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_transaction_id():
        from django.utils.crypto import get_random_string
        while True:
            date_part = timezone.localdate().strftime('%Y%m%d')
            random_part = get_random_string(8).upper()
            candidate = f'RM-{date_part}-{random_part}'
            if not PaymentTransaction.objects.filter(transaction_id=candidate).exists():
                return candidate

    def can_transition_to(self, new_status):
        new_status = self.PaymentStatus(new_status)
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, set())
        return new_status in allowed


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    duration_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class UserSubscription(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACTIVE', 'Active'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled'),
    ]

    SOURCE_CHOICES = [
        ('PAYMENT', 'Payment'),
        ('ADMIN', 'Admin'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='PAYMENT')
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['user', 'end_date']),
        ]

    def __str__(self):
        return f'{self.user.username} - {self.plan.name} ({self.status})'
