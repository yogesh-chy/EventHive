import logging
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.cache import (
    acquire_seat_lock,
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


# ---- DTO ----
class CheckoutItem:
    __slots__ = ("tier_id", "quantity")

    def __init__(self, tier_id: str, quantity: int):
        self.tier_id  = str(tier_id)
        self.quantity = int(quantity)


# ---- Reference generation ---- 
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


# ---- Pre-conditions ---
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


# ---- Create order ----
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

    acquired_locks = _acquire_order_seat_locks(attendee, items)

    try:
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
                attendee=attendee,
                event=event,
                reference=generate_order_reference(),
                status=OrderStatus.PENDING,
                total_amount=total_amount,
                currency=getattr(getattr(event, "org", None), "currency", "USD"),
                idempotency_key=generate_idempotency_key(),
                expires_at=timezone.now() + timedelta(minutes=ORDER_EXPIRY_MINUTES),
                created_by=attendee,
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
    except Exception:
        _release_checkout_seat_locks(attendee, acquired_locks)
        raise

    invalidate_event_cache(event.slug)
    _broadcast_seat_update(event_id=event.id, event_slug=event.slug)
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


# ---- Attach payment intent ----
def attach_payment_intent(*, order: Order, stripe_payment_intent_id: str) -> Order:
    """
    Record the Stripe PaymentIntent id on the order after the view layer has
    successfully called payment.create_payment_intent(). Pure DB write — no
    Stripe call here.
    """
    order.stripe_payment_intent_id = stripe_payment_intent_id
    order.save(update_fields=["stripe_payment_intent_id", "updated_at"])
    return order


# ---- Confirm order ----
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

        def dispatch_tasks():
            from tasks.tickets import generate_ticket_assets_task
            tickets = Ticket.objects.filter(order_item__order=locked)
            for ticket in tickets:
                generate_ticket_assets_task.delay(str(ticket.id))
        
        transaction.on_commit(dispatch_tasks)

    _release_order_seat_locks(order)
    invalidate_order_cache(order.reference)
    logger.info("Order confirmed: ref=%s payment_intent=%s", order.reference, payment_intent_id)
    return locked


# ---- Cancel order ----
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
    _broadcast_seat_update(event_id=order.event_id, event_slug=order.event.slug)
    logger.info("Order cancelled: ref=%s actor=%s", order.reference, getattr(actor, "pk", actor))
    return locked


# ---- Refund order ----
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
    _broadcast_seat_update(event_id=order.event_id, event_slug=order.event.slug)
    logger.info("Order refunded: ref=%s actor=%s", order.reference, getattr(actor, "pk", actor))
    return locked


# --- Expire stale pending orders ----
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


# ---- Helpers ----
def _broadcast_seat_update(*, event_id, event_slug: str) -> None:
    from apps.events.models import Event as EventModel
    from services.realtime import broadcast_seat_update

    event = EventModel.objects.filter(id=event_id).only("id", "total_capacity", "tickets_sold").first()
    if event is None:
        return
    broadcast_seat_update(event_slug, event.seats_remaining)


def _dispatch_ticket_asset_generation(order: Order) -> None:
    from tasks.tickets import generate_ticket_assets_task

    ticket_ids = list(Ticket.objects.filter(order_item__order=order).values_list("id", flat=True))

    for ticket_id in ticket_ids:
        transaction.on_commit(lambda tid=ticket_id: generate_ticket_assets_task.delay(str(tid)))


def _release_order_seat_locks(order: Order) -> None:
    try:
        for item in order.items.all():
            release_seat_lock(str(item.tier_id), str(order.attendee_id))
    except Exception:
        logger.exception("Failed to release seat locks for order ref=%s", order.reference)


def _acquire_order_seat_locks(attendee, items: list[CheckoutItem]) -> list[str]:
    acquired: list[str] = []
    for item in items:
        if not acquire_seat_lock(item.tier_id, str(attendee.id), item.quantity):
            _release_checkout_seat_locks(attendee, acquired)
            raise SeatAlreadyReservedError(
                "You already have a temporary hold for one of these ticket tiers. "
                "Complete or cancel the pending checkout before trying again."
            )
        acquired.append(item.tier_id)
    return acquired


def _release_checkout_seat_locks(attendee, tier_ids: list[str]) -> None:
    for tier_id in tier_ids:
        release_seat_lock(str(tier_id), str(attendee.id))

