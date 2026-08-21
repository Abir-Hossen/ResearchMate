# ResearchMate — Payment Testing Guide (Phase 4.2.1)

This document explains how to configure, run, and manually test the SSLCOMMERZ
**sandbox payment initiation** flow. It covers Phase 4.2.1 only.

> **Phase status**
> - Payment initiation is implemented (User → SubscriptionPlan → PaymentTransaction → Gateway → PENDING).
> - Payment verification is **NOT** implemented yet (Phase 4.3).
> - `PaymentTransaction` is **never** set to `SUCCESS` automatically in this phase.
> - Premium access is **never** activated automatically in this phase.
> - Phase 4.3 will handle verified payment callbacks (success/fail/cancel/IPN) and Premium activation.
>
> **Sandbox payments do not transfer real money.**

---

## 1. Configure SSLCOMMERZ sandbox credentials

SSLCOMMERZ is configured entirely through environment variables. Credentials are
**never** hardcoded and are **never** committed to the repository.

Copy `.env.example` to `.env` (if not already present) and fill in your sandbox
credentials from the SSLCOMMERZ sandbox merchant panel:

```ini
SSLCOMMERZ_STORE_ID=your_sandbox_store_id
SSLCOMMERZ_STORE_PASSWORD=your_sandbox_store_password
SSLCOMMERZ_SANDBOX=True
SSLCOMMERZ_SUCCESS_URL=http://localhost:8000/subscriptions/payment/success/
SSLCOMMERZ_FAIL_URL=http://localhost:8000/subscriptions/payment/fail/
SSLCOMMERZ_CANCEL_URL=http://localhost:8000/subscriptions/payment/cancel/
```

| Variable | Purpose |
| --- | --- |
| `SSLCOMMERZ_STORE_ID` | Sandbox store ID |
| `SSLCOMMERZ_STORE_PASSWORD` | Sandbox store password |
| `SSLCOMMERZ_SANDBOX` | `True` for sandbox, `False` for live |
| `SSLCOMMERZ_SUCCESS_URL` | Gateway success redirect (informational only) |
| `SSLCOMMERZ_FAIL_URL` | Gateway fail redirect (informational only) |
| `SSLCOMMERZ_CANCEL_URL` | Gateway cancel redirect (informational only) |

If these are missing, checkout fails **gracefully**: the transaction is marked
`FAILED`, the user sees "Payment service is currently unavailable. Please try
again later.", and no secrets are exposed.

---

## 2. Required `.env` variables

See the table above. No real credentials should appear in this file or in git.

---

## 3. Run migrations

```bash
python manage.py migrate
```

Migration `0004_update_plan_prices` finalizes plan data:

| Plan | slug | duration_days | price (BDT) | is_active |
| --- | --- | --- | --- | --- |
| Premium Weekly | `premium-weekly` | 7 | 99.00 | True |
| Premium Monthly | `premium-monthly` | 30 | 299.00 | True |

Historical `PaymentTransaction.amount` snapshots are **not** changed.

---

## 4. Run the project

```bash
python manage.py runserver
```

Visit http://localhost:8000/

---

## 5. Login

- Register a new account at `/register/`, or
- Log in at `/login/`.

> When arriving from the landing page, the `next` parameter returns you safely
> to `/subscriptions/pricing/` after login. The `next` URL is validated with
> Django's `url_has_allowed_host_and_scheme` to prevent open redirects.

---

## 6. Visit the pricing page

Go to `/subscriptions/pricing/`. The page displays:

- **Basic** — Free
- **Premium Weekly** — ৳99.00 (7-day access), from the database
- **Premium Monthly** — ৳299.00 (30-day access), from the database

Prices and durations are read from `SubscriptionPlan` records — they are never
hardcoded in templates.

---

## 7. Initiate Premium Weekly payment

On the pricing page, submit the **Premium Weekly** POST form (`Pay ৳99.00`).
This:

1. Creates a `PaymentTransaction` (`INITIATED`)
2. Calls the SSLCOMMERZ sandbox to create a payment session
3. Marks the transaction `PENDING`
4. Redirects the browser to the SSLCOMMERZ `GatewayPageURL`

---

## 8. Initiate Premium Monthly payment

Submit the **Premium Monthly** POST form (`Pay ৳299.00`). Same flow as above.

> Payments must be initiated via **POST** (CSRF-protected). They cannot be
> initiated via GET.

---

## 9. Inspect PaymentTransaction in Django Admin

Log in to `/admin/`, open **Subscriptions → Payment transactions**. Each row
shows:

- Transaction ID
- User
- Plan
- Amount
- Currency
- Payment Gateway
- Status
- Gateway Transaction ID
- Initiated At
- Completed At
- Verified At

After initiating checkout, verify the transaction moved `INITIATED → PENDING`.

---

## 10. Expected state transitions

Successful gateway session creation:

```
INITIATED
    ↓
PENDING
```

Gateway initiation failure (missing credentials, network error, invalid
response, missing gateway URL):

```
INITIATED
    ↓
FAILED
```

---

## 11. Manual verification checklist

- [ ] Premium Weekly price = ৳99.00 in DB and on the pricing page
- [ ] Premium Monthly price = ৳299.00 in DB and on the pricing page
- [ ] Anonymous landing "Upgrade" → `/accounts/login/?next=/subscriptions/pricing/`
- [ ] Authenticated user → landing "Upgrade" → `/subscriptions/pricing/`
- [ ] Pricing page loads prices dynamically from the database
- [ ] Checkout uses POST + CSRF
- [ ] Missing credentials → transaction `FAILED`, safe message shown, no secrets leaked
- [ ] Successful (mocked) gateway initiation → transaction `PENDING`
- [ ] No `SUCCESS` status is created
- [ ] No `UserSubscription` is activated
- [ ] Basic user remains Basic; Premium user remains Premium
- [ ] All Premium feature protection still works

---

## 12. Run the test suite

```bash
python manage.py test
```

All existing and new tests must pass.
