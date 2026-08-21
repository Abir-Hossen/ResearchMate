from django.contrib import admin

from .models import PaymentTransaction, SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'price', 'duration_days', 'is_active', 'created_at')
    list_filter = ('is_active', 'duration_days')
    search_fields = ('name', 'slug', 'description')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'start_date', 'end_date', 'created_at')
    list_filter = ('status', 'plan', 'start_date', 'end_date')
    search_fields = ('user__username', 'user__email', 'plan__name')
    readonly_fields = ('created_at', 'updated_at')


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
