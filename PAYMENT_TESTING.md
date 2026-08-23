# Payment Testing Guide — SSLCOMMERZ Sandbox

This document explains how to manually complete a successful SSLCOMMERZ Sandbox payment in ResearchMate, and how to inspect the resulting database state.

---

## Prerequisites

1. Django server running locally.
2. SSLCOMMERZ Sandbox credentials configured in `.env`.
3. A user account in ResearchMate.

### Required `.env` Variables

```
SSLCOMMERZ_STORE_ID=your_sandbox_store_id
SSLCOMMERZ_STORE_PASSWORD=your_sandbox_store_password
SSLCOMMERZ_SANDBOX=True
SSLCOMMERZ_SUCCESS_URL=http://localhost:8000/subscriptions/payment/success/
SSLCOMMERZ_FAIL_URL=http://localhost:8000/subscriptions/payment/fail/
SSLCOMMERZ_CANCEL_URL=http://localhost:8000/subscriptions/payment/cancel/
```

Do NOT hardcode credentials in source code, logs, or documentation.

---

## How to Complete a Successful SSLCOMMERZ Sandbox Payment

### Step 1 — Start Django Server

```bash
python manage.py runserver
```

### Step 2 — Login to ResearchMate

Open `http://localhost:8000/accounts/login/` and log in with a valid user account.

### Step 3 — Open Pricing Page

Navigate to `http://localhost:8000/subscriptions/pricing/`

You should see:
- Premium Weekly (৳99.00, 7-day access)
- Premium Monthly (৳299.00, 30-day access)

### Step 4 — Select a Plan

Click the **Subscribe** or **Pay** button for either Premium Weekly or Premium Monthly.

### Step 5 — Confirm Transaction Becomes PENDING

Open Django Admin (`http://localhost:8000/admin/`) and go to **Subscriptions → Payment transactions**.

You should see a new transaction with:
- **Status**: PENDING
- **User**: your logged-in user
- **Plan**: the plan you selected
- **Amount**: matches the plan price
- **Currency**: BDT

### Step 6 — Complete the Sandbox Payment

You will be redirected to the SSLCOMMERZ Sandbox payment page.

Follow the instructions in the **Payment Method Overview** section below to complete the payment using your chosen method.

The Sandbox gateway will show a **SUCCESS** status after the test payment is completed.

### Step 7 — Return to ResearchMate

After clicking **Submit** or **Pay** on the Sandbox gateway, you will be redirected back to ResearchMate.

You should see:
- **Outcome**: success
- **Premium access activated**: Yes
- **Plan name**: the plan you selected
- **Expires date**: the calculated expiry date

### Step 8 — Verify PaymentTransaction Becomes SUCCESS

In Django Admin → **Payment transactions**, refresh the transaction.

You should see:
- **Status**: SUCCESS
- **Completed at**: timestamp of verification
- **Verified at**: timestamp of verification
- **Gateway transaction ID**: the `val_id` from SSLCOMMERZ (starts with `VAL-` or similar)
- **Gateway response**: JSON from the validation API

### Step 9 — Verify UserSubscription Becomes ACTIVE

In Django Admin → **Subscriptions → User subscriptions**, you should see:
- **User**: your logged-in user
- **Plan**: the plan you selected
- **Status**: ACTIVE
- **Start date**: current date/time
- **End date**: start date + plan duration (7 or 30 days)

### Step 10 — Verify Premium Features Are Accessible

Try accessing premium features:
- `http://localhost:8000/papers/` → upload a paper
- `http://localhost:8000/papers/{paper_id}/technical/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/sections/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/glossary/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/flashcards/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/quiz/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/viva/` → should load successfully
- `http://localhost:8000/papers/{paper_id}/notes/` → should load successfully

### Step 11 — Verify Dashboard Shows Active Premium Plan

Navigate to `http://localhost:8000/accounts/dashboard/`

You should see:
- **Plan**: Premium Weekly / Premium Monthly
- **Status**: ACTIVE
- **Days remaining**: calculated from end date

---

## How to Inspect Transaction Details

### Via Django Admin

1. Go to `http://localhost:8000/admin/`
2. Navigate to **Subscriptions → Payment transactions**
3. Click on the transaction to view details

Fields to inspect:
- **transaction_id**: Format `RM-YYYYMMDD-XXXXXX`
- **status**: Should be SUCCESS after successful payment
- **gateway_transaction_id**: Should contain the `val_id` from SSLCOMMERZ
- **gateway_response**: Full JSON response from validation API
- **failure_reason**: Should be empty for successful transactions
- **amount**: Historical payment amount snapshot
- **currency**: Should be BDT
- **completed_at / verified_at**: Timestamps

### Via Django Shell

```python
python manage.py shell
```

```python
from subscriptions.models import PaymentTransaction, UserSubscription
from subscriptions.services import user_has_premium_access, get_active_subscription
from django.contrib.auth.models import User

user = User.objects.get(username='your_username')

# List all transactions for the user
for txn in user.payment_transactions.all().order_by('-created_at'):
    print(f"{txn.transaction_id} | {txn.status} | {txn.amount} {txn.currency} | val_id={txn.gateway_transaction_id}")

# Check active subscription
subscription = get_active_subscription(user)
if subscription:
    print(f"Active: {subscription.plan.name} until {subscription.end_date}")
else:
    print("No active subscription")

# Check premium access
print(f"Has premium: {user_has_premium_access(user)}")
```

---

## Payment Method Overview

### A. VISA Card

1. On the Sandbox gateway, select **VISA** as the card type.
2. Enter any 16-digit card number (e.g., `4111111111111111`).
3. Enter any future expiry date (e.g., `12/30`).
4. Enter any 3-digit CVV (e.g., `123`).
5. Enter any name on card.
6. Click **Pay**.
7. No OTP is required for VISA on the Sandbox.
8. The gateway will show SUCCESS and redirect back to ResearchMate.

### B. Mastercard

1. On the Sandbox gateway, select **Mastercard** as the card type.
2. Enter any 16-digit Mastercard number (e.g., `5555555555554444`).
3. Enter any future expiry date (e.g., `12/30`).
4. Enter any 3-digit CVV (e.g., `123`).
5. Enter any name on card.
6. Click **Pay**.
7. No OTP is required for Mastercard on the Sandbox.
8. The gateway will show SUCCESS and redirect back to ResearchMate.

### C. American Express

1. On the Sandbox gateway, select **American Express** as the card type.
2. Enter any 15-digit Amex number (e.g., `378282246310005`).
3. Enter any future expiry date (e.g., `12/30`).
4. Enter any 4-digit CVV (e.g., `1234`).
5. Enter any name on card.
6. Click **Pay**.
7. No OTP is required for Amex on the Sandbox.
8. The gateway will show SUCCESS and redirect back to ResearchMate.

### D. Mobile Banking / Mobile OTP

1. On the Sandbox gateway, select the desired mobile banking option (e.g., bKash, Nagad, Rocket).
2. Enter any 11-digit mobile number (e.g., `01700000000`).
3. The Sandbox gateway will simulate the mobile banking flow.
4. If OTP is requested, enter the Sandbox OTP: **123456**.
5. Click **Confirm** or **Submit**.
6. The gateway will show SUCCESS and redirect back to ResearchMate.

**Important Notes for Mobile Banking:**
- The Sandbox gateway simulates the mobile banking flow. The mobile number input may depend on the selected simulated gateway and is not necessarily a real mobile banking account.
- The Sandbox OTP value `123456` is the official test OTP for this environment.
- No real money is deducted during Sandbox testing.

---

## Troubleshooting

### Payment Shows SUCCESS in Gateway but ResearchMate Says "Could Not Verify"

This is the bug that was fixed. Possible causes if it recurs:

1. **Missing `val_id` in callback**: The success callback must include `val_id`. If the gateway does not send it, the verification cannot proceed.
2. **Network error during validation**: The validation API call may have failed. The transaction will remain PENDING (not FAILED) for retry.
3. **Amount/currency mismatch**: The validated amount or currency does not match the local transaction snapshot.

### How to Inspect Logs

Check the Django console output for SSLCOMMERZ log messages:

```
SSLCOMMERZ success callback received: method=POST, tran_id=RM-..., val_id=VAL-..., keys=[...]
SSLCOMMERZ verification connection error for RM-...: ...
SSLCOMMERZ verification returned non-success status for RM-...: ...
SSLCOMMERZ amount mismatch for RM-...: ...
SSLCOMMERZ currency mismatch for RM-...: ...
SSLCOMMERZ tran_id mismatch for RM-...: ...
```

### How to Retry a Pending Verification

If a transaction is stuck in PENDING due to a network error:

1. Ensure the gateway dashboard shows SUCCESS for the transaction.
2. Visit the success URL manually with the callback parameters:
   ```
   http://localhost:8000/subscriptions/payment/success/?tran_id=RM-...&val_id=VAL-...
   ```
3. The verification will be retried.

---

## Security Notes

- Store credentials are never logged or exposed in templates.
- The `failure_reason` field contains safe technical descriptions only.
- Server-side validation is always performed before Premium access is granted.
- Callback data is never trusted for payment outcomes.
- The `user` and `plan` fields are determined by the local database transaction, not by callback parameters.
