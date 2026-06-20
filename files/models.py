"""
apps/orders/models.py  ·  PHASE 3  (re-aligned to blueprint — adds Payments fields)

Models: Order, OrderItem, Ticket, ProcessedStripeEvent

CHANGES FROM PREVIOUS VERSION (re-alignment to EventHive_Architecture.pdf):
  - Order.reference        NEW  — 8-char unique slug, used in URLs (/orders/{ref}/)
                                  instead of the UUID id, per blueprint API spec.
  - Order.idempotency_key  NEW  — unique, generated at order creation. Passed to
                                  Stripe as the idempotency header so retried
                                  requests after a network failure never double-charge.
  - Order.payment_intent_id renamed → stripe_payment_intent_id, now unique+nullable
                                  (blueprint: "stripe_payment_intent_id (unique)").
  - Order.confirmed_at,
    Order.cancelled_at      NEW  — explicit timestamps per blueprint, instead of
                                  relying on updated_at.
  - Ticket.attendee_name,
    Ticket.attendee_email   NEW  — denormalized snapshot captured at purchase
                                  time. Per blueprint: tickets can be addressed
                                  to someone other than the purchasing attendee
                                  (e.g. buying for a friend); this field exists
                                  for that, defaulting to the attendee's own info.
  - Ticket.pdf_url          NEW  — S3 key for the generated PDF ticket (Phase 4
                                  populates this; field exists now so the
                                  migration doesn't need to run twice).
  - Ticket.is_checked_in    NEW  — read-only property mirroring blueprint's
                                  boolean field name. Backed by `status` rather
                                  than a separate boolean column, because a
                                  plain boolean cannot also represent
                                  TicketStatus.CANCELLED — collapsing that
                                  distinction would silently break cancel_order().
  - ProcessedStripeEvent    NEW  — idempotent webhook processing per blueprint:
                                  "Webhook handler first checks stripe_event_id
                                  in processed_events table — skip if seen."

DEVIATION FROM BLUEPRINT (documented, not silent):
  Blueprint's Ticket has unique_together: (order, tier) with no quantity field
  and no OrderItem model. Taken literally, that allows at most ONE ticket per
  tier per order — i.e. nobody could buy 2 "General" tickets in a single
  checkout. That breaks the core purchase flow the blueprint itself describes
  ("Atomic Ticket Purchase" — tier availability checked per request, not
  capped at 1). OrderItem is kept as the quantity-tracking layer between Order
  and Ticket; Ticket continues to reference OrderItem rather than Order+Tier
  directly. unique_together(order, tier) is intentionally NOT applied.

PREDICTED PROBLEMS ADDRESSED (carried over + new):
  1.  Overselling under concurrency → select_for_update() in services.py.
  2.  Price drift → unit_price snapshotted on OrderItem at creation.
  3.  Decimal-only arithmetic → no FloatField anywhere.
  4.  Abandoned PENDING orders → expires_at + Celery expiry task.
  5.  Double-submit → existing-pending-order check in services.py.
  6.  Event.tickets_sold drift → F() updates in the same transaction.
  7.  QR code collision → uuid4().hex callable default + DB unique constraint.
  8.  Checked-in ticket cancelled → TicketStatus.USED blocks cancel.
  9.  Deleting a User/Event with orders → on_delete=PROTECT.
 10.  STRIPE DOUBLE CHARGE on retry → idempotency_key passed to Stripe API
      calls (see payment.py); duplicate webhook delivery → ProcessedStripeEvent
      guard in webhook_views.py.
 11.  Order reference collision → generate_order_reference() in services.py
      retries on collision, same pattern as Event slug generation in Phase 2.
 12.  stripe_payment_intent_id uniqueness with NULL values → field uses
      null=True (not blank="" ) so multiple un-paid orders can coexist;
      PostgreSQL treats multiple NULLs as distinct under a unique constraint,
      but multiple empty strings would violate it.
"""

import uuid as _uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel


# ── Status choices ─────────────────────────────────────────────────────────────

class OrderStatus(models.TextChoices):
    PENDING   = "PENDING",   "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    REFUNDED  = "REFUNDED",  "Refunded"


class TicketStatus(models.TextChoices):
    VALID     = "VALID",     "Valid"
    USED      = "USED",      "Used"
    CANCELLED = "CANCELLED", "Cancelled"


ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PENDING:   {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.REFUNDED,  OrderStatus.CANCELLED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED:  set(),
}


# ── Order ──────────────────────────────────────────────────────────────────────

class Order(BaseModel):
    """
    Top-level purchase record.

    reference: public-facing 8-char identifier used in URLs, e.g.
      GET /api/v1/orders/A7K2P9XQ/
    Generated by services.generate_order_reference() — never by the model's
    default= (would bypass collision retry logic).

    idempotency_key: generated once at order creation, passed to every Stripe
    API call related to this order. If the client retries a failed request
    (e.g. browser timeout), the same key is reused, so Stripe recognises the
    retry and returns the original result instead of charging twice.
    """

    attendee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    reference = models.CharField(
        max_length=8,
        unique=True,
        db_index=True,
        help_text="Public 8-char order reference. Used in URLs instead of the UUID id.",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Sum of all OrderItem subtotals. Snapshotted at creation.",
    )
    currency = models.CharField(max_length=3, default="USD")

    idempotency_key = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        default=None,
        help_text="Sent as the Stripe idempotency header. Null until Stripe call is made.",
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        default=None,
        db_index=True,
        help_text="Stripe PaymentIntent ID. Null until payment is initiated.",
    )

    expires_at    = models.DateTimeField(null=True, blank=True, db_index=True)
    confirmed_at  = models.DateTimeField(null=True, blank=True)
    cancelled_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "orders"
        ordering  = ["-created_at"]
        indexes   = [
            models.Index(fields=["attendee", "status"],    name="order_attendee_status_idx"),
            models.Index(fields=["event",    "status"],    name="order_event_status_idx"),
            models.Index(fields=["status",   "expires_at"], name="order_status_expires_idx"),
        ]

    def __str__(self) -> str:
        return f"Order {self.reference} — {self.status}"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ORDER_STATUS_TRANSITIONS.get(self.status, set())

    @property
    def is_expired(self) -> bool:
        if self.status != OrderStatus.PENDING or self.expires_at is None:
            return False
        return timezone.now() > self.expires_at


# ── OrderItem ──────────────────────────────────────────────────────────────────

class OrderItem(BaseModel):
    """
    One line in an order: quantity of a specific TicketTier.
    See module docstring "DEVIATION FROM BLUEPRINT" for why this exists.
    unit_price is an immutable price snapshot taken at order creation.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    tier  = models.ForeignKey(
        "events.TicketTier",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity   = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        app_label = "orders"
        indexes   = [models.Index(fields=["order", "tier"], name="orderitem_order_tier_idx")]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="orderitem_quantity_positive"),
            models.CheckConstraint(check=models.Q(unit_price__gte=0), name="orderitem_price_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.quantity}× tier {self.tier_id} in Order {self.order_id}"

    @property
    def subtotal(self):
        return self.unit_price * self.quantity


# ── Ticket ─────────────────────────────────────────────────────────────────────

class Ticket(BaseModel):
    """
    One physical ticket. One row per quantity unit, created via bulk_create.

    attendee_name / attendee_email: snapshot at issuance. Defaults to the
    purchasing attendee's own name/email but can be overridden per-ticket
    in a future "buy for a friend" flow (not built in Phase 3 — field exists
    so the schema doesn't need to change again later).

    is_checked_in: blueprint names this a boolean field. Implemented as a
    property over `status` instead of a literal BooleanField, because a
    boolean cannot also encode TicketStatus.CANCELLED — see module docstring.
    """

    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="tickets")
    attendee   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets",
    )
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="tickets")
    tier  = models.ForeignKey("events.TicketTier", on_delete=models.PROTECT, related_name="tickets")

    attendee_name  = models.CharField(max_length=255, blank=True, default="")
    attendee_email = models.EmailField(blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.VALID,
        db_index=True,
    )
    qr_code = models.CharField(
        max_length=64,
        unique=True,
        default=lambda: _uuid.uuid4().hex,
        help_text="Unique token for QR code generation. UUIDv4 hex.",
    )
    pdf_url = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="S3/R2 key for the generated PDF ticket. Populated in Phase 4.",
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "orders"
        ordering  = ["created_at"]
        indexes   = [
            models.Index(fields=["event",    "status"], name="ticket_event_status_idx"),
            models.Index(fields=["attendee", "status"], name="ticket_attendee_status_idx"),
            models.Index(fields=["qr_code"],            name="ticket_qr_code_idx"),
        ]

    def __str__(self) -> str:
        return f"Ticket {self.qr_code[:8]}… ({self.status})"

    @property
    def is_checked_in(self) -> bool:
        return self.status == TicketStatus.USED


# ── ProcessedStripeEvent ────────────────────────────────────────────────────────

class ProcessedStripeEvent(models.Model):
    """
    Idempotent webhook guard. Per blueprint:
      "Webhook handler first checks stripe_event_id in processed_events
       table — skip if seen."

    No BaseModel inheritance — this table is purely a dedup ledger, not a
    domain entity. No soft delete, no created_by; just an append-only log.
    """

    id              = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    stripe_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type      = models.CharField(max_length=100)
    processed_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "orders"
        ordering  = ["-processed_at"]

    def __str__(self) -> str:
        return f"{self.stripe_event_id} ({self.event_type})"
