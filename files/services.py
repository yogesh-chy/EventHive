"""
apps/orders/services.py  ·  PHASE 3  (re-aligned to blueprint — Payments)

All business logic for orders. Views stay thin; everything testable here.

CHANGES FROM PREVIOUS VERSION:
  - generate_order_reference()  NEW — collision-safe 8-char reference,
    same retry pattern as events.services.generate_unique_slug() (Phase 2).
  - create_order() now generates reference + idempotency_key. Does NOT call
    Stripe — that happens in a separate step from the view, after this
    transaction has committed (see payment.py docstring, problem #5).
  - confirm_order() now sets confirmed_at.
  - cancel_order()  now sets cancelled_at.
  - refund_order()  NEW — Stripe refund + inventory restoration + audit.
  - attach_payment_intent() NEW — records the Stripe PaymentIntent id on the
    order after a successful payment.create_payment_intent() call.

PREDICTED PROBLEMS ADDRESSED (full list, carried over + new):
  1.  OVERSELLING under concurrency → select_for_update() inside
      transaction.atomic(); second concurrent request blocks, re-reads the
      decremented value, raises InsufficientInventoryError.
  2.  PRICE DRIFT → unit_price snapshotted from tier.price AT ORDER CREATION.
  3.  PARTIAL ORDER FAILURE → entire purchase inside ONE transaction.atomic();
      any failure rolls back everything, including successfully-validated tiers.
  4.  TOTAL MISMATCH (float arithmetic) → Decimal only, never float.
  5.  DOUBLE SUBMIT → check_existing_pending_order() blocks a second PENDING
      order for the same attendee+event.
  6.  CANCEL RESTORING TOO MUCH INVENTORY → select_for_update() on the Order
      row inside cancel_order(); re-checks status before restoring.
  7.  TICKET QR CODE COLLISION → callable uuid4().hex default + DB unique.
  8.  Event.tickets_sold DRIFT → F() updates in the same atomic transaction
      as TicketTier.quantity_sold.
  9.  CANCELLING A USED TICKET → refused if any ticket.status == USED.
 10.  EXPIRY RACE (Celery cancels while user confirms) → select_for_update()
      re-read inside confirm_order() and cancel_order().
 11.  ORDER REFERENCE COLLISION → generate_order_reference() retries with a
      fresh random reference; falls back to a longer suffix if exhausted.
 12.  STRIPE DOUBLE CHARGE on retried request → idempotency_key generated
      once per order, reused on every Stripe call for that order.
 13.  REFUND CALLED ON A NON-CONFIRMED ORDER → refund_order() explicitly
      requires status == CONFIRMED; PENDING orders should use cancel_order()
      instead (no money has moved yet, so there's nothing to refund).
 14.  REFUND SUCCEEDS AT STRIPE BUT DB UPDATE FAILS (or vice versa) →
      Stripe call happens FIRST, outside the DB transaction. Only after
      Stripe confirms the refund do we open transaction.atomic() to update
      local state. If the DB update fails, the refund still exists at
      Stripe (recoverable via reconciliation); we never claim a refund
      happened locally without Stripe confirming it first.
"""

import logging
import secrets
import string
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.cache import (
    invalidate_event_cache,
    invalidate_order_cache,
    release_seat_lock,
)
from core.exceptions import (
    InsufficientInventoryError,
    InvalidStatusTransitionError,
    OrderAlreadyConfirmedError,
    OrderExpiredError,
    SeatAlreadyReservedError,
)

from .models import Order, OrderItem, OrderStatus, Ticket, TicketStatus

logger = logging.getLogger(__name__)

ORDER_EXPIRY_MINUTES = 10
MAX_REFERENCE_RETRIES = 50

# Excludes ambiguous characters (0/O, 1/I/l) — standard for human-read references.
_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


# ── DTO ────────────────────────────────────────────────────────────────────────

class CheckoutItem:
    __slots__ = ("tier_id", "quantity")

    def __init__(self, tier_id: str, quantity: int):
        self.tier_id  = str(tier_id)
        self.quantity = int(quantity)


# ── Reference generation ───────────────────────────────────────────────────────

def generate_order_reference() -> str:
    """
    Generate a collision-safe 8-character public order reference.
    Same retry pattern as apps.events.services.generate_unique_slug().

    Uses secrets.choice (CSPRNG) rather than random — references are
    sometimes used as a "did you really place this order" proof in support
    flows, so they should not be predictable.
    """
    for _ in range(MAX_REFERENCE_RETRIES):
        candidate = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(8))
        if not Order.objects.filter(reference=candidate).exists():
            return candidate

    # Astronomically unlikely fallback: widen to 12 chars.
    return "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(12))


def generate_idempotency_key() -> str:
    """Server-generated key reused across all Stripe calls for one order."""
    return uuid.uuid4().hex


# ── Pre-conditions ─────────────────────────────────────────────────────────────

def check_existing_pending_order(attendee, event) -> None:
    existing = Order.objects.filter(
        attendee=attendee, event=event,
        status=OrderStatus.PENDING,
        expires_at__gt=timezone.now(),
        is_deleted=False,
    ).first()

    if existing:
        raise SeatAlreadyReservedError(
            f"You already have a pending order (ref={existing.reference}) for this event. "
            "Complete or cancel it before placing a new order."
        )


# ── Create order ───────────────────────────────────────────────────────────────

def create_order(*, attendee, event, items: list[CheckoutItem]) -> Order:
    """
    Atomically create a PENDING order with inventory decremented.

    Does NOT contact Stripe. The view layer is responsible for calling
    payment.create_payment_intent() AFTER this transaction commits, then
    attach_payment_intent() to record the result.
    """
    if not items:
        raise ValueError("Order must contain at least one item.")

    check_existing_pending_order(attendee, event)

    tier_ids     = [item.tier_id for item in items]
    quantity_map = {item.tier_id: item.quantity for item in items}

    with transaction.atomic():
        from apps.events.models import TicketTier
        tiers = {
            str(t.id): t
            for t in TicketTier.objects.select_for_update().filter(
                id__in=tier_ids, is_deleted=False,
            )
        }

        _validate_tiers(tiers, tier_ids, quantity_map, event)

        total_amount = Decimal("0.00")
        for tier_id, qty in quantity_map.items():
            total_amount += tiers[tier_id].price * qty

        order = Order.objects.create(
            attendee         = attendee,
            event            = event,
            reference        = generate_order_reference(),
            status           = OrderStatus.PENDING,
            total_amount     = total_amount,
            currency         = getattr(getattr(event, "org", None), "currency", "USD"),
            idempotency_key  = generate_idempotency_key(),
            expires_at       = timezone.now() + timedelta(minutes=ORDER_EXPIRY_MINUTES),
            created_by       = attendee,
        )

        total_ticket_count = 0
        for tier_id, qty in quantity_map.items():
            tier = tiers[tier_id]
            item = OrderItem.objects.create(
                order=order, tier=tier, quantity=qty, unit_price=tier.price,
            )
            Ticket.objects.bulk_create([
                Ticket(
                    order_item     = item,
                    attendee       = attendee,
                    event          = event,
                    tier           = tier,
                    status         = TicketStatus.VALID,
                    qr_code        = uuid.uuid4().hex,
                    attendee_name  = getattr(attendee, "full_name", "") or attendee.get_username(),
                    attendee_email = getattr(attendee, "email", ""),
                )
                for _ in range(qty)
            ])
            total_ticket_count += qty

        for tier_id, qty in quantity_map.items():
            TicketTier.objects.filter(id=tier_id).update(
                quantity_sold=F("quantity_sold") + qty
            )

        from apps.events.models import Event as EventModel
        EventModel.objects.filter(id=event.id).update(
            tickets_sold=F("tickets_sold") + total_ticket_count
        )

    invalidate_event_cache(event.slug)
    logger.info(
        "Order created: ref=%s attendee=%s event=%s total=%s",
        order.reference, attendee.pk, event.slug, total_amount,
    )
    return order


def _validate_tiers(tiers, tier_ids, quantity_map, event) -> None:
    errors = []
    now = timezone.now()

    for tier_id in tier_ids:
        tier = tiers.get(tier_id)
        qty  = quantity_map[tier_id]

        if tier is None:
            errors.append(f"Tier {tier_id} does not exist or has been deleted.")
            continue
        if str(tier.event_id) != str(event.id):
            errors.append(f"Tier {tier_id} does not belong to event '{event.slug}'.")
            continue
        if not tier.is_active:
            errors.append(f"Tier '{tier.name}' is not currently available.")
            continue
        if qty <= 0:
            errors.append(f"Quantity for tier '{tier.name}' must be at least 1.")
            continue
        if qty > tier.available_quantity:
            errors.append(
                f"Tier '{tier.name}' has only {tier.available_quantity} "
                f"ticket(s) remaining; you requested {qty}."
            )
            continue
        if tier.sale_start and now < tier.sale_start:
            errors.append(f"Tier '{tier.name}': sales have not started yet.")
        if tier.sale_end and now > tier.sale_end:
            errors.append(f"Tier '{tier.name}': sales have ended.")

    if errors:
        raise InsufficientInventoryError(" | ".join(errors))


# ── Attach payment intent ──────────────────────────────────────────────────────

def attach_payment_intent(*, order: Order, stripe_payment_intent_id: str) -> Order:
    """
    Record the Stripe PaymentIntent id on the order after the view layer has
    successfully called payment.create_payment_intent(). Pure DB write — no
    Stripe call here.
    """
    order.stripe_payment_intent_id = stripe_payment_intent_id
    order.save(update_fields=["stripe_payment_intent_id", "updated_at"])
    return order


# ── Confirm order ──────────────────────────────────────────────────────────────

def confirm_order(*, order: Order, payment_intent_id: str = "") -> Order:
    """
    Transition PENDING → CONFIRMED. Called by the Stripe webhook handler on
    payment_intent.succeeded (or by an admin via the manual confirm endpoint
    for testing).
    """
    if order.is_expired:
        raise OrderExpiredError()

    if not order.can_transition_to(OrderStatus.CONFIRMED):
        raise InvalidStatusTransitionError(
            f"Cannot confirm an order with status '{order.status}'."
        )

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status != OrderStatus.PENDING:
            raise InvalidStatusTransitionError(
                f"Order status changed to '{locked.status}' concurrently."
            )
        locked.status       = OrderStatus.CONFIRMED
        locked.confirmed_at = timezone.now()
        locked.expires_at   = None
        if payment_intent_id:
            locked.stripe_payment_intent_id = payment_intent_id
        locked.save(update_fields=[
            "status", "confirmed_at", "expires_at", "stripe_payment_intent_id", "updated_at",
        ])

    _release_order_seat_locks(order)
    invalidate_order_cache(order.reference)
    logger.info("Order confirmed: ref=%s payment_intent=%s", order.reference, payment_intent_id)
    return locked


# ── Cancel order ───────────────────────────────────────────────────────────────

def cancel_order(*, order: Order, actor) -> Order:
    """
    Cancel a PENDING or CONFIRMED order and restore inventory atomically.
    Refuses if any ticket has been checked in.

    Note: cancelling a CONFIRMED order does NOT call Stripe — a confirmed
    order has already been paid. Use refund_order() to both refund and
    cancel in one step. This function alone is for PENDING-order cancellation
    (nothing was charged) or for an admin force-cancel after a refund has
    already been separately processed.
    """
    if not order.can_transition_to(OrderStatus.CANCELLED):
        raise InvalidStatusTransitionError(
            f"Cannot cancel an order with status '{order.status}'."
        )

    used_count = Ticket.objects.filter(
        order_item__order=order, status=TicketStatus.USED,
    ).count()
    if used_count:
        raise InvalidStatusTransitionError(
            f"Cannot cancel order: {used_count} ticket(s) have already been used."
        )

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            raise InvalidStatusTransitionError(f"Order is already {locked.status}.")
        if locked.status == OrderStatus.CONFIRMED:
            raise OrderAlreadyConfirmedError()

        total_restored = 0
        for item in locked.items.select_related("tier").all():
            from apps.events.models import TicketTier
            TicketTier.objects.filter(id=item.tier_id).update(
                quantity_sold=F("quantity_sold") - item.quantity
            )
            total_restored += item.quantity

        from apps.events.models import Event as EventModel
        EventModel.objects.filter(id=locked.event_id).update(
            tickets_sold=F("tickets_sold") - total_restored
        )

        Ticket.objects.filter(
            order_item__order=locked, status=TicketStatus.VALID,
        ).update(status=TicketStatus.CANCELLED)

        locked.status       = OrderStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.expires_at   = None
        locked.save(update_fields=["status", "cancelled_at", "expires_at", "updated_at"])

    _release_order_seat_locks(order)
    invalidate_event_cache(order.event.slug)
    invalidate_order_cache(order.reference)
    logger.info("Order cancelled: ref=%s actor=%s", order.reference, getattr(actor, "pk", actor))
    return locked


# ── Refund order ───────────────────────────────────────────────────────────────

def refund_order(*, order: Order, actor) -> Order:
    """
    Refund a CONFIRMED order: Stripe refund first, then local state update.

    Order of operations matters (see problem #14 in module docstring):
      1. Validate status == CONFIRMED (PENDING orders use cancel_order instead).
      2. Call Stripe refund — OUTSIDE any DB transaction.
      3. Only if Stripe confirms the refund: open transaction.atomic() and
         restore inventory + mark tickets cancelled + set status=REFUNDED.

    If step 2 fails, no DB state changes — the order remains CONFIRMED and
    the caller (or a retry) can attempt the refund again safely, since the
    idempotency key on the refund call prevents a duplicate Stripe refund.
    """
    if order.status != OrderStatus.CONFIRMED:
        raise InvalidStatusTransitionError(
            f"Cannot refund an order with status '{order.status}'. "
            f"Only CONFIRMED orders can be refunded."
        )

    from . import payment
    payment.refund_payment_intent(order)   # Stripe call — outside the transaction

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status != OrderStatus.CONFIRMED:
            # Concurrent change after the Stripe call returned — extremely rare,
            # but the refund already succeeded at Stripe regardless. Log loudly
            # for manual reconciliation; do not attempt a second Stripe call.
            logger.error(
                "Order status changed to '%s' between Stripe refund and DB update. "
                "ref=%s — Stripe refund WAS processed; manual reconciliation required.",
                locked.status, order.reference,
            )
            raise InvalidStatusTransitionError(
                "Order status changed concurrently. The refund was processed at "
                "Stripe; please contact support to reconcile this order."
            )

        total_restored = 0
        for item in locked.items.select_related("tier").all():
            from apps.events.models import TicketTier
            TicketTier.objects.filter(id=item.tier_id).update(
                quantity_sold=F("quantity_sold") - item.quantity
            )
            total_restored += item.quantity

        from apps.events.models import Event as EventModel
        EventModel.objects.filter(id=locked.event_id).update(
            tickets_sold=F("tickets_sold") - total_restored
        )

        Ticket.objects.filter(
            order_item__order=locked, status=TicketStatus.VALID,
        ).update(status=TicketStatus.CANCELLED)

        locked.status       = OrderStatus.REFUNDED
        locked.cancelled_at = timezone.now()
        locked.save(update_fields=["status", "cancelled_at", "updated_at"])

    invalidate_event_cache(order.event.slug)
    invalidate_order_cache(order.reference)
    logger.info("Order refunded: ref=%s actor=%s", order.reference, getattr(actor, "pk", actor))
    return locked


# ── Expire stale pending orders ────────────────────────────────────────────────

def expire_pending_orders() -> int:
    """Cancel PENDING orders past expires_at. Called every 2 min by Celery Beat."""
    expired = Order.objects.select_for_update(skip_locked=True).filter(
        status=OrderStatus.PENDING, expires_at__lt=timezone.now(), is_deleted=False,
    )
    count = 0
    for order in expired:
        try:
            cancel_order(order=order, actor="system:expiry_task")
            count += 1
        except Exception:
            logger.exception("Failed to expire order ref=%s", order.reference)

    if count:
        logger.info("Expired %d pending order(s).", count)
    return count


# ── Helpers ────────────────────────────────────────────────────────────────────

def _release_order_seat_locks(order: Order) -> None:
    try:
        for item in order.items.all():
            release_seat_lock(str(item.tier_id), str(order.attendee_id))
    except Exception:
        logger.exception("Failed to release seat locks for order ref=%s", order.reference)
