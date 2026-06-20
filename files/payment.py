"""
apps/orders/payment.py  ·  PHASE 3

Thin wrapper around the Stripe Python SDK. Mirrors the blueprint's
services/payment.py module (page 15: "payment.py — Stripe wrapper").

Kept as its own module — separate from services.py — because:
  - It is the only file in the orders app that makes outbound network calls.
  - It can be mocked in tests with a single patch target
    ("apps.orders.payment.stripe") instead of patching scattered calls.
  - services.py stays pure business logic; this stays pure I/O.

PREDICTED PROBLEMS ADDRESSED:
  1. DOUBLE CHARGE on retry — every Stripe call passes idempotency_key.
     If the client retries after a timeout, Stripe recognises the same key
     within a 24-hour window and returns the original PaymentIntent instead
     of creating a second one and charging twice.

  2. FLOAT ROUNDING in amount_in_smallest_unit — Decimal("9.99") * 100 must
     produce exactly 999, never 998 or 999.0000000001. Using Decimal
     arithmetic throughout and converting to int only at the final step
     avoids float entirely.

  3. ZERO-DECIMAL CURRENCIES (JPY, KRW) — Stripe expects these in whole
     units, not /100. Not handled by amount_in_smallest_unit() below;
     flagged with a TODO since EventHive currently only supports USD-style
     2-decimal currencies. Do not assume this function is currency-agnostic.

  4. STRIPE API DOWN / NETWORK ERROR — every call is wrapped in
     stripe.error.StripeError handling and re-raised as the domain-specific
     PaymentFailedError / RefundFailedError so callers never need to import
     the stripe SDK directly.

  5. CALLING STRIPE INSIDE A DB TRANSACTION — intentionally NOT done.
     create_payment_intent() and refund_payment_intent() are called from
     views.py AFTER the DB transaction in services.create_order() /
     services.refund_order() has already committed. A slow or failed
     external API call must never hold open a DB transaction or a
     select_for_update() row lock.

  6. WEBHOOK SIGNATURE FORGERY — verify_webhook_signature() uses
     stripe.Webhook.construct_event(), which validates the HMAC signature
     against STRIPE_WEBHOOK_SECRET. A request without a valid signature
     raises SignatureVerificationError before any order is touched.
"""

import logging
from decimal import Decimal

from django.conf import settings

from core.exceptions import PaymentFailedError, RefundFailedError

logger = logging.getLogger(__name__)

try:
    import stripe
    stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")
except ImportError:  # pragma: no cover
    # Allows the orders app to be imported before `pip install stripe` runs,
    # e.g. during initial migrations. Any actual payment call will fail loudly.
    stripe = None


def _require_stripe():
    if stripe is None:
        raise PaymentFailedError(
            "Stripe SDK is not installed. Run: pip install stripe"
        )


def amount_in_smallest_unit(amount: Decimal) -> int:
    """
    Convert a Decimal currency amount to the integer smallest-unit value
    Stripe expects (e.g. 9.99 USD -> 999 cents).

    TODO (Phase 4+): zero-decimal currencies (JPY, KRW, etc.) must NOT be
    multiplied by 100. This function currently assumes a 2-decimal currency.
    """
    return int((amount * 100).to_integral_value())


# ── PaymentIntent ────────────────────────────────────────────────────────────────

def create_payment_intent(order) -> "stripe.PaymentIntent":
    """
    Create a Stripe PaymentIntent for the given Order.

    Called from views.py AFTER create_order() has committed its DB
    transaction. order.idempotency_key must already be set (done in
    services.create_order()).
    """
    _require_stripe()

    if not order.idempotency_key:
        raise PaymentFailedError(
            "Order is missing an idempotency_key; cannot create a PaymentIntent."
        )

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_in_smallest_unit(order.total_amount),
            currency=order.currency.lower(),
            metadata={
                "order_id":        str(order.id),
                "order_reference": order.reference,
                "event_id":        str(order.event_id),
                "attendee_id":     str(order.attendee_id),
            },
            idempotency_key=order.idempotency_key,
        )
    except stripe.error.StripeError as exc:
        logger.exception(
            "Stripe PaymentIntent creation failed. order_reference=%s", order.reference
        )
        raise PaymentFailedError(f"Payment provider error: {exc.user_message or str(exc)}")

    logger.info(
        "PaymentIntent created. order_reference=%s intent_id=%s",
        order.reference, intent.id,
    )
    return intent


def refund_payment_intent(order) -> "stripe.Refund":
    """
    Refund the full amount of a CONFIRMED order's PaymentIntent.

    Idempotency key is derived deterministically from the order id so a
    retried refund request never creates two refunds for the same order.
    """
    _require_stripe()

    if not order.stripe_payment_intent_id:
        raise RefundFailedError(
            "Order has no associated PaymentIntent; nothing to refund."
        )

    try:
        refund = stripe.Refund.create(
            payment_intent=order.stripe_payment_intent_id,
            idempotency_key=f"refund_{order.id}",
        )
    except stripe.error.StripeError as exc:
        logger.exception(
            "Stripe refund failed. order_reference=%s", order.reference
        )
        raise RefundFailedError(f"Refund provider error: {exc.user_message or str(exc)}")

    logger.info(
        "Refund created. order_reference=%s refund_id=%s",
        order.reference, refund.id,
    )
    return refund


# ── Webhook signature verification ──────────────────────────────────────────────

def verify_webhook_signature(payload: bytes, sig_header: str):
    """
    Verify a Stripe webhook request's signature and return the parsed event.
    Raises stripe.error.SignatureVerificationError if the signature is invalid
    or the payload was tampered with — caller must return 400 in that case.
    """
    _require_stripe()
    webhook_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
