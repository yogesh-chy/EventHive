"""
apps/orders/webhook_views.py  ·  PHASE 3

Stripe webhook handler. Per blueprint:
  POST /api/v1/webhooks/stripe/   Stripe   Payment confirmed / failed webhook

This is a plain Django view (not DRF) because:
  - Stripe sends the raw request body and a signature header that must be
    verified BEFORE any JSON parsing — DRF's request.data would have already
    parsed (and potentially mutated) the body.
  - No DRF authentication applies here; Stripe authenticates via the
    signature, not a Bearer token.

PREDICTED PROBLEMS ADDRESSED:
  1. FORGED WEBHOOK REQUESTS — payment.verify_webhook_signature() validates
     the HMAC signature against STRIPE_WEBHOOK_SECRET. Invalid signature →
     400 before touching any Order.

  2. DUPLICATE WEBHOOK DELIVERY — Stripe retries webhooks that don't return
     2xx, and can occasionally deliver the same event twice even on success.
     ProcessedStripeEvent.objects.create(stripe_event_id=...) relies on the
     unique constraint as the actual race-condition guard: if two deliveries
     arrive concurrently, only one create() succeeds; the other catches
     IntegrityError and treats it as "already processed".

  3. CSRF MIDDLEWARE BLOCKING THE WEBHOOK — Stripe cannot supply a Django
     CSRF token. @csrf_exempt is required on this view specifically; the
     signature check is the actual security boundary, not CSRF.

  4. SLOW HANDLER CAUSING STRIPE RETRY STORM — Stripe expects a response
     within ~10 seconds or it will retry. The handler here only updates a
     few rows in one transaction; if Phase 4 adds e.g. PDF generation, that
     work MUST be dispatched to Celery, not run synchronously in this view.

  5. UNKNOWN / UNHANDLED EVENT TYPES — events are returned 200 with a
     no-op response rather than erroring, since Stripe sends many event
     types and we only care about two of them. Returning anything other
     than 2xx for an event we deliberately ignore would cause needless
     retries.

  6. ORDER NOT FOUND for a PaymentIntent (e.g. a PaymentIntent created
     outside our flow, or a stale/duplicate metadata mismatch) — handled
     defensively; logs and returns 200 (we cannot "fix" this by retrying,
     and re-delivery from Stripe will not change the outcome).
"""

import logging

from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import payment, services
from .models import Order, ProcessedStripeEvent

logger = logging.getLogger(__name__)

_HANDLED_EVENT_TYPES = {"payment_intent.succeeded", "payment_intent.payment_failed"}


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    POST /api/v1/webhooks/stripe/

    Always returns 2xx for events we successfully process OR deliberately
    ignore, so Stripe does not retry unnecessarily. Returns 400 only for
    signature verification failures (Stripe will not retry these — the
    payload is presumed malicious or malformed, retrying won't help).
    """
    payload    = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = payment.verify_webhook_signature(payload, sig_header)
    except Exception:
        logger.warning("Stripe webhook signature verification failed.")
        return HttpResponseBadRequest("Invalid signature.")

    event_id   = event["id"]
    event_type = event["type"]

    # ── Idempotency guard ────────────────────────────────────────────────────
    # The unique constraint on stripe_event_id is the real race-condition
    # guard; this try/except just makes concurrent duplicate deliveries
    # resolve to "already processed" instead of crashing.
    try:
        with transaction.atomic():
            ProcessedStripeEvent.objects.create(
                stripe_event_id=event_id,
                event_type=event_type,
            )
    except IntegrityError:
        logger.info("Stripe event %s already processed; skipping.", event_id)
        return HttpResponse(status=200)

    if event_type not in _HANDLED_EVENT_TYPES:
        logger.debug("Ignoring unhandled Stripe event type: %s", event_type)
        return HttpResponse(status=200)

    intent            = event["data"]["object"]
    stripe_intent_id  = intent.get("id", "")

    order = Order.objects.filter(
        stripe_payment_intent_id=stripe_intent_id, is_deleted=False,
    ).first()

    if order is None:
        logger.error(
            "Stripe event %s references unknown PaymentIntent %s. "
            "No matching Order found — cannot process.",
            event_id, stripe_intent_id,
        )
        return HttpResponse(status=200)  # don't trigger a retry; this won't change

    try:
        if event_type == "payment_intent.succeeded":
            services.confirm_order(order=order, payment_intent_id=stripe_intent_id)
            logger.info(
                "Webhook confirmed order ref=%s via Stripe event %s", order.reference, event_id
            )

        elif event_type == "payment_intent.payment_failed":
            services.cancel_order(order=order, actor="system:stripe_webhook")
            logger.info(
                "Webhook cancelled order ref=%s via Stripe event %s", order.reference, event_id
            )

    except Exception:
        # State-machine errors here (e.g. order already confirmed by the
        # manual test endpoint) are logged but still return 200 — retrying
        # the webhook will not resolve a state-machine conflict.
        logger.exception(
            "Failed to apply Stripe event %s to order ref=%s", event_id, order.reference
        )

    return HttpResponse(status=200)
