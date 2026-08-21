import logging

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .models import SubscriptionPlan
from .services import (
    create_payment_transaction,
    get_current_subscription_status,
    mark_transaction_pending,
    mark_transaction_failed,
)
from .sslcommerz_service import (
    SSLCommerzError,
    initiate_sslcommerz_payment,
    is_sslcommerz_configured,
)

logger = logging.getLogger(__name__)


@login_required(login_url='login')
def pricing_view(request):
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('duration_days')
    subscription_status = get_current_subscription_status(request.user)
    return render(request, 'subscriptions/pricing.html', {
        'plans': plans,
        'subscription_status': subscription_status,
    })


@login_required(login_url='login')
def checkout_view(request, plan_slug):
    if request.method != 'POST':
        return redirect('subscriptions:pricing')

    plan = get_object_or_404(SubscriptionPlan, slug=plan_slug, is_active=True)

    transaction = create_payment_transaction(request.user, plan)

    if not is_sslcommerz_configured():
        logger.warning('Checkout attempted but SSLCOMMERZ credentials are not configured.')
        mark_transaction_failed(transaction, reason='Payment service is currently unavailable.')
        messages.error(
            request,
            'Payment service is currently unavailable. Please try again later.'
        )
        return redirect('subscriptions:pricing')

    try:
        gateway_url = initiate_sslcommerz_payment(transaction, request)
    except SSLCommerzError as exc:
        mark_transaction_failed(transaction, reason=str(exc))
        messages.error(
            request,
            'Payment service is currently unavailable. Please try again later.'
        )
        return redirect('subscriptions:pricing')

    mark_transaction_pending(transaction)
    return redirect(gateway_url)


@login_required(login_url='login')
def payment_return_view(request, outcome):
    messages.info(
        request,
        'Your payment is being processed. Premium access will be activated only after secure verification.'
    )
    return render(request, 'subscriptions/payment_return.html', {'outcome': outcome})
