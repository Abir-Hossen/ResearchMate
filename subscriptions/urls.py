from django.urls import path

from .views import checkout_view, payment_return_view, pricing_view

app_name = 'subscriptions'

urlpatterns = [
    path('pricing/', pricing_view, name='pricing'),
    path('checkout/<slug:plan_slug>/', checkout_view, name='checkout'),
    path('payment/success/', payment_return_view, {'outcome': 'success'}, name='payment_success'),
    path('payment/fail/', payment_return_view, {'outcome': 'fail'}, name='payment_fail'),
    path('payment/cancel/', payment_return_view, {'outcome': 'cancel'}, name='payment_cancel'),
]
