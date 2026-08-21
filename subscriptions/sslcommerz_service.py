import json
import logging

import requests
from django.conf import settings

from .models import PaymentTransaction

logger = logging.getLogger(__name__)


class SSLCommerzError(Exception):
    """Raised when SSLCOMMERZ payment initiation fails for any reason."""


def is_sandbox():
    return bool(getattr(settings, 'SSLCOMMERZ_SANDBOX', True))


def is_sslcommerz_configured():
    """Return True only when the minimum required gateway credentials are set.

    Used to fail gracefully (instead of producing an unclear gateway error) when
    a developer has not configured sandbox credentials.
    """
    store_id = getattr(settings, 'SSLCOMMERZ_STORE_ID', '')
    store_password = getattr(settings, 'SSLCOMMERZ_STORE_PASSWORD', '')
    return bool(store_id) and bool(store_password)


def get_api_endpoint():
    if is_sandbox():
        return 'https://sandbox.sslcommerz.com/gwprocess/v4/api.php'
    return 'https://securepay.sslcommerz.com/gwprocess/v4/api.php'


def _safe_json(value):
    try:
        return json.dumps(value, default=str)
    except TypeError:
        return json.dumps({'raw': str(value)}, default=str)


def initiate_sslcommerz_payment(transaction, request=None):
    if not isinstance(transaction, PaymentTransaction):
        raise SSLCommerzError('A valid PaymentTransaction is required.')

    if transaction.status != PaymentTransaction.PaymentStatus.INITIATED:
        raise SSLCommerzError(
            f'Transaction {transaction.transaction_id} is not eligible for initiation '
            f'(current status: {transaction.status}).'
        )

    store_id = getattr(settings, 'SSLCOMMERZ_STORE_ID', '')
    store_password = getattr(settings, 'SSLCOMMERZ_STORE_PASSWORD', '')

    user = transaction.user
    payload = {
        'store_id': store_id,
        'store_passwd': store_password,
        'total_amount': str(transaction.amount),
        'currency': transaction.currency,
        'tran_id': transaction.transaction_id,
        'success_url': getattr(settings, 'SSLCOMMERZ_SUCCESS_URL', ''),
        'fail_url': getattr(settings, 'SSLCOMMERZ_FAIL_URL', ''),
        'cancel_url': getattr(settings, 'SSLCOMMERZ_CANCEL_URL', ''),
        'cus_name': (user.get_full_name() or user.username)[:50],
        'cus_email': (user.email or '')[:50],
        'cus_phone': '',
        'cus_addr1': 'ResearchMate',
        'cus_city': '',
        'cus_country': 'Bangladesh',
        'shipping_method': 'NO',
        'product_name': transaction.plan.name,
        'product_category': 'Subscription',
        'product_profile': 'non-physical-goods',
    }

    try:
        response = requests.post(get_api_endpoint(), data=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.warning('SSLCOMMERZ connection error for %s: %s', transaction.transaction_id, exc)
        transaction.gateway_response = _safe_json({'error': 'gateway_connection_error'})
        transaction.save(update_fields=['gateway_response', 'updated_at'])
        raise SSLCommerzError('Gateway connection error') from exc

    try:
        data = response.json()
    except ValueError:
        transaction.gateway_response = _safe_json({'error': 'invalid_gateway_response', 'body': response.text[:500]})
        transaction.save(update_fields=['gateway_response', 'updated_at'])
        raise SSLCommerzError('Invalid gateway response')

    gateway_url = data.get('GatewayPageURL')
    if data.get('status') != 'SUCCESS' or not gateway_url:
        transaction.gateway_response = _safe_json(data)
        transaction.save(update_fields=['gateway_response', 'updated_at'])
        raise SSLCommerzError('Gateway did not return a payment session')

    transaction.gateway_response = _safe_json(data)
    if data.get('sessionkey'):
        transaction.gateway_transaction_id = data['sessionkey']
    transaction.save(update_fields=['gateway_response', 'gateway_transaction_id', 'updated_at'])

    return gateway_url
