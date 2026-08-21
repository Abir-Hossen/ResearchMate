from django.contrib import admin
from django.contrib import messages
from django.shortcuts import render
from django.utils import timezone

from .models import PaymentTransaction, SubscriptionPlan, UserSubscription
from .services import (
    extend_subscription,
    grant_manual_subscription,
    revoke_subscription,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price', 'duration_days', 'is_active', 'created_at')
    list_filter = ('is_active', 'duration_days')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'source', 'start_date', 'end_date', 'created_at')
    list_filter = ('status', 'plan', 'source', 'start_date', 'end_date')
    search_fields = ('user__username', 'user__email', 'plan__name')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['admin_grant_premium', 'admin_revoke_premium', 'admin_extend_premium']

    @admin.action(description='Grant Premium access (manual)')
    def admin_grant_premium(self, request, queryset):
        if 'apply' in request.POST:
            plan_id = request.POST.get('plan')
            if not plan_id:
                self.message_user(request, 'Please select a plan.', messages.ERROR)
                return
            plan = SubscriptionPlan.objects.filter(pk=plan_id, is_active=True).first()
            if not plan:
                self.message_user(request, 'Selected plan is not active.', messages.ERROR)
                return
            count = 0
            for subscription in queryset:
                grant_manual_subscription(subscription.user, plan)
                count += 1
            self.message_user(request, f'Granted Premium access to {count} user(s).', messages.SUCCESS)
            return
        plans = SubscriptionPlan.objects.filter(is_active=True)
        return render(request, 'admin/subscriptions/grant_premium_intermediate.html', {
            'subscriptions': queryset,
            'plans': plans,
            'action': 'admin_grant_premium',
            'title': 'Grant Premium Access',
        })

    @admin.action(description='Revoke Premium access')
    def admin_revoke_premium(self, request, queryset):
        count = 0
        for subscription in queryset:
            result = revoke_subscription(subscription.user)
            if result:
                count += 1
        self.message_user(request, f'Revoked Premium access for {count} subscription(s).', messages.SUCCESS)

    @admin.action(description='Extend Premium access by days')
    def admin_extend_premium(self, request, queryset):
        if 'apply' in request.POST:
            try:
                days = int(request.POST.get('days', 0))
            except (TypeError, ValueError):
                days = 0
            if days <= 0:
                self.message_user(request, 'Extension days must be a positive integer.', messages.ERROR)
                return
            count = 0
            errors = 0
            for subscription in queryset:
                try:
                    extend_subscription(subscription.user, days)
                    count += 1
                except Exception:
                    errors += 1
            msg = f'Extended {count} subscription(s) by {days} day(s).'
            if errors:
                msg += f' Skipped {errors} subscription(s) due to errors.'
            self.message_user(request, msg, messages.SUCCESS)
            return
        return render(request, 'admin/subscriptions/extend_premium_intermediate.html', {
            'subscriptions': queryset,
            'action': 'admin_extend_premium',
            'title': 'Extend Premium Access',
        })


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'user',
        'plan',
        'amount',
        'currency',
        'payment_gateway',
        'status',
        'gateway_transaction_id',
        'initiated_at',
        'completed_at',
        'verified_at',
    )
    list_filter = ('status', 'payment_gateway', 'plan', 'created_at')
    search_fields = ('transaction_id', 'gateway_transaction_id', 'user__username', 'user__email')
    readonly_fields = ('transaction_id', 'amount', 'currency', 'initiated_at', 'created_at', 'updated_at')
