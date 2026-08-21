from django.urls import path

from .views import (
    checkout_view,
    payment_cancel_view,
    payment_debug_verify_view,
    payment_fail_view,
    payment_success_view,
    pricing_view,
)

app_name = 'subscriptions'

urlpatterns = [
    path('pricing/', pricing_view, name='pricing'),
    path('checkout/<slug:plan_slug>/', checkout_view, name='checkout'),
    path('payment/success/', payment_success_view, name='payment_success'),
    path('payment/fail/', payment_fail_view, name='payment_fail'),
    path('payment/cancel/', payment_cancel_view, name='payment_cancel'),
    path('debug/verify/<str:transaction_id>/', payment_debug_verify_view, name='payment_debug_verify'),
]
