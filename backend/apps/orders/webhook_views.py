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
