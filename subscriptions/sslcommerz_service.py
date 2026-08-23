import json
import logging

import requests
from decimal import Decimal
from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from .models import PaymentTransaction
from .services import activate_subscription

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


def get_validation_endpoint():
    if is_sandbox():
        return 'https://sandbox.sslcommerz.com/validator/api/validationserverAPI.php'
    return 'https://securepay.sslcommerz.com/validator/api/validationserverAPI.php'


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


def verify_sslcommerz_payment(transaction, callback_data=None, val_id=None):
    """Verify a payment server-side with SSLCOMMERZ.

    This never trusts the browser redirect or callback payload for the outcome.
    It calls the SSLCOMMERZ validation API using ``val_id`` (the gateway
    validation session ID from the success callback) and then compares the
    verified gateway response against the database ``PaymentTransaction``
    snapshot (amount, currency, tran_id).

    ``val_id`` is extracted from ``callback_data`` when provided, or can be
    passed directly. If neither is available, verification cannot proceed.

    Raises ``SSLCommerzError`` when verification fails for any reason.
    Returns the validated gateway data dict on success.
    """
    if not isinstance(transaction, PaymentTransaction):
        raise SSLCommerzError('A valid PaymentTransaction is required.')

    if transaction.status not in (
        PaymentTransaction.PaymentStatus.INITIATED,
        PaymentTransaction.PaymentStatus.PENDING,
    ):
        raise SSLCommerzError(
            f'Transaction {transaction.transaction_id} is not in a verifiable state '
            f'(status={transaction.status}).'
        )

    if not is_sslcommerz_configured():
        raise SSLCommerzError('Payment gateway is not configured for verification.')

    extracted_val_id = val_id
    if extracted_val_id is None and callback_data:
        extracted_val_id = callback_data.get('val_id')

    if not extracted_val_id:
        raise SSLCommerzError(
            'Missing val_id. Server-side order validation requires the gateway '
            'validation session ID from the success callback.'
        )

    store_id = getattr(settings, 'SSLCOMMERZ_STORE_ID', '')
    store_password = getattr(settings, 'SSLCOMMERZ_STORE_PASSWORD', '')

    params = {
        'val_id': extracted_val_id,
        'store_id': store_id,
        'store_passwd': store_password,
        'v': '1',
        'format': 'json',
    }

    logger.info(
        'SSLCOMMERZ validation request for %s (val_id=%s): endpoint=%s',
        transaction.transaction_id,
        extracted_val_id,
        get_validation_endpoint(),
    )

    try:
        response = requests.get(get_validation_endpoint(), params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.warning(
            'SSLCOMMERZ verification connection error for %s (val_id=%s): %s',
            transaction.transaction_id, extracted_val_id, exc,
        )
        raise SSLCommerzError('Payment verification service unavailable.') from exc

    try:
        data = response.json()
    except ValueError:
        logger.warning(
            'SSLCOMMERZ verification returned invalid JSON for %s (val_id=%s): %s',
            transaction.transaction_id, extracted_val_id, response.text[:500],
        )
        raise SSLCommerzError('Invalid verification response from gateway.')

    logger.info(
        'SSLCOMMERZ validation API response for %s (val_id=%s): %s',
        transaction.transaction_id,
        extracted_val_id,
        _safe_json(data),
    )

    status = (data.get('status') or '').upper()
    if status not in ('VALID', 'VALIDATED'):
        logger.warning(
            'SSLCOMMERZ verification returned non-success status for %s (val_id=%s): %s',
            transaction.transaction_id, extracted_val_id, status,
        )
        raise SSLCommerzError('Payment verification failed.')

    if data.get('tran_id') and data['tran_id'] != transaction.transaction_id:
        logger.warning(
            'SSLCOMMERZ tran_id mismatch for %s (val_id=%s): expected=%s got=%s',
            transaction.transaction_id, extracted_val_id,
            transaction.transaction_id, data.get('tran_id'),
        )
        raise SSLCommerzError('Transaction identifier mismatch during verification.')

    try:
        verified_amount = Decimal(str(data.get('amount', '')))
    except Exception:
        raise SSLCommerzError('Invalid amount in verification response.')

    if verified_amount != transaction.amount:
        logger.warning(
            'SSLCOMMERZ amount mismatch for %s (val_id=%s): verified=%s expected=%s',
            transaction.transaction_id, extracted_val_id,
            verified_amount, transaction.amount,
        )
        raise SSLCommerzError('Payment amount mismatch during verification.')

    if (data.get('currency') or '').upper() != transaction.currency.upper():
        logger.warning(
            'SSLCOMMERZ currency mismatch for %s (val_id=%s): expected=%s got=%s',
            transaction.transaction_id, extracted_val_id,
            transaction.currency, data.get('currency'),
        )
        raise SSLCommerzError('Currency mismatch during verification.')

    return data


def verify_and_complete_payment(transaction, callback_data=None, val_id=None):
    """Verify a payment and, only on success, atomically mark it SUCCESS and
    activate the Premium subscription.

    Idempotent: if the transaction is already ``SUCCESS`` it is returned without
    re-activating. Uses ``select_for_update`` + ``transaction.atomic`` so a
    duplicate callback cannot create a duplicate subscription, and so that a
    failure during activation rolls back the SUCCESS marking (never leaving a
    SUCCESS transaction without an active subscription).
    """
    validated = verify_sslcommerz_payment(transaction, callback_data=callback_data, val_id=val_id)

    with db_transaction.atomic():
        locked = PaymentTransaction.objects.select_for_update().get(pk=transaction.pk)

        if locked.status == PaymentTransaction.PaymentStatus.SUCCESS:
            return locked

        if locked.status not in (
            PaymentTransaction.PaymentStatus.INITIATED,
            PaymentTransaction.PaymentStatus.PENDING,
        ):
            raise SSLCommerzError(
                f'Transaction {locked.transaction_id} cannot be completed from status {locked.status}.'
            )

        now = timezone.now()
        locked.status = PaymentTransaction.PaymentStatus.SUCCESS
        locked.completed_at = now
        locked.verified_at = now
        locked.gateway_response = _safe_json(validated)
        gateway_val_id = validated.get('val_id')
        if gateway_val_id:
            locked.gateway_transaction_id = gateway_val_id
        locked.save(update_fields=[
            'status', 'completed_at', 'verified_at',
            'gateway_response', 'gateway_transaction_id', 'updated_at',
        ])

        try:
            activate_subscription(locked.user, locked.plan)
        except Exception as exc:
            logger.exception(
                'Subscription activation failed for %s after successful verification',
                locked.transaction_id,
            )
            raise SSLCommerzError('Subscription activation failed after payment verification.') from exc

    return locked
