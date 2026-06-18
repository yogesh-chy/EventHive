import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.cache import invalidate_event_cache, invalidate_order_cache, release_seat_lock
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


# ---- DTO ----
class CheckoutItem:
    __slots__ = ("tier_id", "quantity")

    def __init__(self, tier_id: str, quantity: int):
        self.tier_id = str(tier_id)
        self.quantity = int(quantity)


# ---- Pre-Conditions ----
def check_existing_pending_order(attendee, event) -> None:
    existing = Order.objects.filter(
        attendee=attendee,
        event=event,
        status=OrderStatus.PENDING,
        expires_at__gt=timezone.now(),
        is_deleted=False
    ).first()
    
    if existing:
        raise SeatAlreadyReservedError(
            f"You already have a pending order(id={existing.id}) for this event. "
            "Complete or cancel it before placing a new order."
        )
    

# ---- Create Order ----
def create_order(*, attendee, event, items: list[CheckoutItem]) -> Order:
    if not items:
        raise ValueError("Order must contain at least one item.")
    
    check_existing_pending_order(attendee, event)

    tier_ids = [item.tier_id for item in items]
    quantity_map = {item.tier_id: item.quantity for item in items}

    with transaction.atomic():
        from apps.events.models import TicketTier
        tiers = {
            str(t.id): t
            for t in TicketTier.objects.select_for_update().filter(id__in=tier_ids, is_deleted=False)
        }

        _validate_tiers(tiers, tier_ids, quantity_map, event)

        # --- Compute Decimal Total ---
        total_amount = Decimal("0.00")
        for tier_id, qty in quantity_map.items():
            total_amount += tiers[tier_id].price * qty
        
        # --- Create Order ---
        order = Order.objects.create(
            attendee     = attendee,
            event        = event,
            status       = OrderStatus.PENDING,
            total_amount = total_amount,
            currency     = getattr(getattr(event, "org", None), "currency", "USD"),
            expires_at   = timezone.now() + timedelta(minutes=ORDER_EXPIRY_MINUTES),
            created_by   = attendee
        )

        # --- Create OrderItems + Tickets ---
        total_ticket_count = 0
        for tier_id, qty in quantity_map.items():
            t_tier = tiers[tier_id]
            item = OrderItem.objects.create(order=order,tier=t_tier,quantity=qty,unit_price=t_tier.price)
            Ticket.objects.bulk_create([
                Ticket(
                    order_item = item,
                    attendee   = attendee,
                    event      = event,
                    tier       = t_tier,
                    status     = TicketStatus.VALID,
                    qr_code    = uuid.uuid4().hex
                )
                for _ in range(qty)
            ])
            total_ticket_count += qty
        
        # --- Decrement inventory with F() ---
        for tier_id, qty in quantity_map.items():
            TicketTier.objects.filter(id=tier_id).update(quantity_sold=F("quantity_sold") + qty)
        
        # --- Increment Event.tickets_sold ---
        from apps.events.models import Event as EventModel
        EventModel.objects.filter(id=event.id).update(tickets_sold=F("tickets_sold") + total_ticket_count)
    
    invalidate_event_cache(event.slug)
    logger.info(
        "Order created: id=%s attendee=%s event=%s total=%s",
        order.id, attendee.pk, event.slug, total_amount
    )
    return order

def _validate_tiers(tiers, tier_ids, quantity_map, event) -> None:
    errors = []
    now = timezone.now()

    for tier_id in tier_ids:
        tier = tiers.get(tier_id)
        qty = quantity_map[tier_id]

        if tier is None:
            errors.append(f"Tier {tier_id} does not exist or has been deleted.")
            continue

        if str(tier.event_id) != str(event.id):
            errors.append(f"Tier {tier_id} does not belong to event '{event.slug}'.")
            continue

        if not tier.is_active:
            errors.append(f"Tier {tier_id} is not currently available.")
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


# ---- Confirm Order ----
def confirm_order(*, order: Order, payment_intent_id: str = "") -> Order:

    if order.is_expired:
        raise OrderExpiredError()
    
    if not order.can_transition_to(OrderStatus.CONFIRM):
        raise InvalidStatusTransitionError(f"Cannot confirm an order with status '{order.status}'.")

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        
        if locked.status != OrderStatus.PENDING:
            raise InvalidStatusTransitionError(f"Order status changed to '{locked.status}' concurrently.")
        locked.status = OrderStatus.CONFIRM
        locked.payment_intent_id = payment_intent_id
        locked.expires_at = None
        locked.save(update_fields=["status","payment_intent_id","expires_at","updated_at"])

    _release_order_seat_locks(order)
    invalidate_order_cache(str(order.id))
    logger.info("Order confirmed: id=%s payment_intent=%s", order.id, payment_intent_id)
    return locked


# ---- Cancel Order ----
def cancel_order(*, order: Order, actor) -> Order:

    if not order.can_transition_to(OrderStatus.CANCELLED):
        raise InvalidStatusTransitionError(f"Cannot cancel an order with status '{order.status}'.")
    
    used_count = Ticket.objects.filter(order_item__order=order,status=TicketStatus.USED).count()

    if used_count:
        raise InvalidStatusTransitionError(f"Cannot cancel order: {used_count} ticket(s) have already been used.")
    
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
            raise InvalidStatusTransitionError(f"Order is already {locked.status}.")
        if locked.status == OrderStatus.CONFIRM:
            raise OrderAlreadyConfirmedError()
    
        # --- Restore Inventory ----
        total_restored = 0
        for item in locked.items.select_related("tier").all():
            from apps.events.models import TicketTier
            TicketTier.objects.filter(id=item.tier_id).update(quantity_sold=F("quantity_sold") - item.quantity)
            total_restored += item.quantity

        from apps.events.models import Event as EventModel
        EventModel.objects.filter(id=locked.event_id).update(tickets_sold=F("tickets_sold") - total_restored)

        Ticket.objects.filter(order_item__order=locked,status=TicketStatus.VALID).update(status=TicketStatus.CANCELLED)

        locked.status = OrderStatus.CANCELLED
        locked.expires_at = None
        locked.save(update_fields=["status","expires_at","updated_at"])

    _release_order_seat_locks(order)
    invalidate_event_cache(order.event.slug)
    invalidate_order_cache(str(order.id))
    logger.info("Order cancelled: id=%s actor=%s", order.id, getattr(actor, "pk", actor))
    return locked


# ---- Expire stale pending order ----
def expire_pending_orders() -> int:
    expired_ids = list(Order.objects.filter(
        status=OrderStatus.PENDING,
        expires_at__lt=timezone.now(),
        is_deleted=False
    ).values_list("id", flat=True))

    count = 0
    for order_id in expired_ids:
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update(skip_locked=True).filter(pk=order_id).first()
                if order:
                    cancel_order(order=order, actor="system:expiry_task")
                    count += 1
        except Exception:
            logger.exception("Failed to expire order id=%s", order_id)
    
    if count:
        logger.info("Expired %d pending order(s).", count)
    return count


# ---- Helpers ----
def _release_order_seat_locks(order: Order) -> None:
    try:
        for item in order.items.all():
            release_seat_lock(str(item.tier_id), str(order.attendee_id))
    except Exception:
        logger.exception("Failed to release seat locks for order id=%s", order.id)