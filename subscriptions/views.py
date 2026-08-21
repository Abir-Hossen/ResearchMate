import logging

import requests
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.utils import timezone
from django.http import HttpResponse
from django.utils import timezone

from .models import PaymentTransaction, SubscriptionPlan
from .services import (
    activate_subscription,
    create_payment_transaction,
    extend_subscription,
    get_active_subscription,
    get_current_subscription_status,
    grant_manual_subscription,
    mark_transaction_cancelled,
    mark_transaction_failed,
    mark_transaction_pending,
    revoke_subscription,
    user_has_premium_access,
)
from .sslcommerz_service import (
    SSLCommerzError,
    initiate_sslcommerz_payment,
    is_sslcommerz_configured,
    verify_and_complete_payment,
    get_validation_endpoint,
    is_sandbox,
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


@csrf_exempt
def payment_success_view(request):
    callback_data = {}
    if request.method == 'POST':
        callback_data.update(request.POST.dict())
    if request.GET:
        callback_data.update(request.GET.dict())
    if request.content_type and 'json' in request.content_type.lower():
        try:
            import json
            callback_data.update(json.loads(request.body.decode('utf-8') or '{}'))
        except (ValueError, UnicodeDecodeError):
            pass

    tran_id = callback_data.get('tran_id')
    val_id = callback_data.get('val_id')

    safe_keys = sorted([k for k in callback_data.keys() if k not in ('store_passwd', 'password', 'secret')])
    safe_values = {k: callback_data[k] for k in safe_keys if k not in ('store_passwd', 'password', 'secret')}
    logger.info(
        'SSLCOMMERZ success callback received: method=%s, content_type=%s, tran_id=%s, val_id=%s, keys=%s, values=%s',
        request.method,
        request.content_type,
        tran_id,
        val_id,
        safe_keys,
        safe_values,
    )

    if not tran_id:
        messages.info(
            request,
            'We are verifying your payment. Premium access will be activated once verification completes.'
        )
        return render(request, 'subscriptions/payment_return.html', {
            'outcome': 'success',
            'activated': False,
        })

    try:
        transaction = PaymentTransaction.objects.get(transaction_id=tran_id)
    except PaymentTransaction.DoesNotExist:
        messages.error(request, 'We could not find your payment record. Please contact support.')
        return render(request, 'subscriptions/payment_return.html', {
            'outcome': 'success',
            'activated': False,
            'not_found': True,
        })

    if transaction.status == PaymentTransaction.PaymentStatus.SUCCESS:
        subscription = get_active_subscription(transaction.user)
        return render(request, 'subscriptions/payment_return.html', {
            'outcome': 'success',
            'activated': True,
            'plan_name': transaction.plan.name,
            'expires_date': subscription.end_date if subscription else None,
        })

    try:
        transaction = verify_and_complete_payment(transaction, callback_data=callback_data, val_id=val_id)
    except SSLCommerzError as exc:
        logger.warning('Payment verification failed for %s: %s', tran_id, exc)
        if transaction.status not in (
            PaymentTransaction.PaymentStatus.SUCCESS,
            PaymentTransaction.PaymentStatus.FAILED,
            PaymentTransaction.PaymentStatus.CANCELLED,
        ):
            transaction.failure_reason = str(exc)
            transaction.save(update_fields=['failure_reason', 'updated_at'])
        messages.error(
            request,
            'We could not verify your payment. Please contact support if any amount was deducted.'
        )
        return render(request, 'subscriptions/payment_return.html', {
            'outcome': 'fail',
            'activated': False,
        })

    subscription = get_active_subscription(transaction.user)
    return render(request, 'subscriptions/payment_return.html', {
        'outcome': 'success',
        'activated': True,
        'plan_name': transaction.plan.name,
        'expires_date': subscription.end_date if subscription else None,
    })


@csrf_exempt
def payment_fail_view(request):
    _mark_terminal_callback(request, 'fail')
    return render(request, 'subscriptions/payment_return.html', {'outcome': 'fail'})


@csrf_exempt
def payment_cancel_view(request):
    _mark_terminal_callback(request, 'cancel')
    return render(request, 'subscriptions/payment_return.html', {'outcome': 'cancel'})


@login_required(login_url='login')
def payment_debug_verify_view(request, transaction_id):
    """Diagnostic view to manually test SSLCOMMERZ validation for a transaction."""
    if not request.user.is_staff:
        return HttpResponse('Staff only', status=403)

    transaction = get_object_or_404(PaymentTransaction, transaction_id=transaction_id)
    val_id = transaction.gateway_transaction_id

    store_id = settings.SSLCOMMERZ_STORE_ID
    store_password = settings.SSLCOMMERZ_STORE_PASSWORD

    payload = {
        'val_id': val_id,
        'store_id': store_id,
        'store_passwd': store_password,
        'format': 'json',
    }

    endpoint = get_validation_endpoint()
    sandbox = is_sandbox()

    result = {
        'transaction_id': transaction.transaction_id,
        'status': transaction.status,
        'amount': str(transaction.amount),
        'currency': transaction.currency,
        'gateway_transaction_id': transaction.gateway_transaction_id,
        'sandbox': sandbox,
        'endpoint': endpoint,
        'payload_sent': {
            'val_id': val_id,
            'store_id': store_id,
            'format': 'json',
        },
        'request_error': None,
        'response_status': None,
        'response_body': None,
        'parsed_status': None,
        'validation_error': None,
    }

    try:
        response = requests.post(endpoint, data=payload, timeout=30)
        result['response_status'] = response.status_code
        result['response_body'] = response.text[:2000]
        try:
            data = response.json()
            result['parsed_status'] = data.get('status')
            result['response_body'] = data
        except ValueError:
            result['validation_error'] = 'Response is not valid JSON'
    except requests.exceptions.RequestException as exc:
        result['request_error'] = str(exc)

    lines = [f'Transaction: {transaction.transaction_id}']
    lines.append(f'Status: {transaction.status}')
    lines.append(f'Amount: {transaction.amount} {transaction.currency}')
    lines.append(f'Gateway Transaction ID (val_id): {val_id}')
    lines.append(f'Sandbox: {sandbox}')
    lines.append(f'Endpoint: {endpoint}')
    lines.append(f'Payload: val_id={val_id}, store_id={store_id}, format=json')
    lines.append('')
    if result['request_error']:
        lines.append(f'REQUEST ERROR: {result["request_error"]}')
    else:
        lines.append(f'Response HTTP Status: {result["response_status"]}')
        lines.append(f'Parsed Status: {result["parsed_status"]}')
        lines.append(f'Response Body: {result["response_body"]}')
        if result['validation_error']:
            lines.append(f'Validation Error: {result["validation_error"]}')

    return HttpResponse('<pre>' + '\n'.join(lines) + '</pre>', content_type='text/plain')


def _mark_terminal_callback(request, kind):
    callback_data = request.POST if request.method == 'POST' else request.GET
    tran_id = callback_data.get('tran_id')
    if not tran_id:
        return
    transaction = PaymentTransaction.objects.filter(transaction_id=tran_id).first()
    if transaction is None:
        return
    if kind == 'fail':
        if transaction.status in (
            PaymentTransaction.PaymentStatus.INITIATED,
            PaymentTransaction.PaymentStatus.PENDING,
        ):
            mark_transaction_failed(transaction, reason='Payment failed at gateway.')
    else:
        if transaction.status in (
            PaymentTransaction.PaymentStatus.INITIATED,
            PaymentTransaction.PaymentStatus.PENDING,
        ):
            mark_transaction_cancelled(transaction)


@login_required(login_url='login')
def my_subscription_view(request):
    user = request.user
    user_has_premium_access(user)
    subscription_status = get_current_subscription_status(user)
    active_subscription = get_active_subscription(user)
    recent_subscription = user.subscriptions.order_by('-created_at').first()
    context = {
        'subscription_status': subscription_status,
        'active_subscription': active_subscription,
        'recent_subscription': recent_subscription,
    }
    return render(request, 'subscriptions/my_subscription.html', context)


@login_required(login_url='login')
def payment_history_view(request):
    transactions = request.user.payment_transactions.all().order_by('-created_at')
    context = {
        'transactions': transactions,
    }
    return render(request, 'subscriptions/payment_history.html', context)


@login_required(login_url='login')
def subscription_history_view(request):
    subscriptions = request.user.subscriptions.all().order_by('-created_at')
    context = {
        'subscriptions': subscriptions,
    }
    return render(request, 'subscriptions/subscription_history.html', context)
