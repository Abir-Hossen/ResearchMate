from django.urls import path

from .views import (
    checkout_view,
    my_subscription_view,
    payment_cancel_view,
    payment_debug_verify_view,
    payment_fail_view,
    payment_history_view,
    payment_success_view,
    pricing_view,
    subscription_history_view,
)

app_name = 'subscriptions'

urlpatterns = [
    path('pricing/', pricing_view, name='pricing'),
    path('my-subscription/', my_subscription_view, name='my_subscription'),
    path('payment-history/', payment_history_view, name='payment_history'),
    path('subscription-history/', subscription_history_view, name='subscription_history'),
    path('checkout/<slug:plan_slug>/', checkout_view, name='checkout'),
    path('payment/success/', payment_success_view, name='payment_success'),
    path('payment/fail/', payment_fail_view, name='payment_fail'),
    path('payment/cancel/', payment_cancel_view, name='payment_cancel'),
    path('debug/verify/<str:transaction_id>/', payment_debug_verify_view, name='payment_debug_verify'),
]
