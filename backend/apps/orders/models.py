import uuid as _uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import BaseModel


# ---- Status Choices ----
class OrderStatus(models.TextChoices):
    PENDING = "PENDING", 'Pending'
    CONFIRM = "CONFIRM", 'confirm'
    CANCELLED = "CANCELLED", 'cancelled'
    REFUNDED = "REFUNDED", 'refunded'

class TicketStatus(models.TextChoices):
    VALID = "VALID", 'Valid'
    USED = "USED", 'Used'
    CANCELLED = "CANCELLED", 'Cancelled'

# --- Valid state-machine transitions ---
ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRM, OrderStatus.CANCELLED},
    OrderStatus.CONFIRM: {OrderStatus.REFUNDED, OrderStatus.CANCELLED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set()
}


# ---- Order ----
class Order(BaseModel):
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING,db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Sum of all OrderItem subtotals. Snapshotted at creation.")
    currency = models.CharField(max_length=3, default="USD", help_text="ISO 4217 currency code.")
    payment_intent_id = models.CharField(max_length=225, blank=True, default="", db_index=True, help_text="Payment provider reference. Populated in Phase 4.")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True, help_text="PENDING order expiry timestamp. Null after confirm/cancel.")

    class Meta:
        app_label = "orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["attendee", "status"], name="order_attendee_status_idx"),
            models.Index(fields=["event", "status"], name="order_event_status_idx"),
            models.Index(fields=["status", "expires_at"], name="order_status_expires_idx")
        ]

    def __str__(self):
        return f"Order {self.id} - {self.status}"
    
    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ORDER_STATUS_TRANSITIONS.get(self.status, set())
    
    @property
    def is_expired(self) -> bool:
        if self.status != OrderStatus.PENDING:
            return False
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at
    

# ---- OrderItem ----
class OrderItem(BaseModel):
    order = models.ForeignKey(Order,on_delete=models.CASCADE,related_name="items")
    tier = models.ForeignKey("events.TicketTier",on_delete=models.PROTECT,related_name="order_items")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10,decimal_places=2,help_text="Tier price at time of purchase. Never updated.")

    class Meta:
        app_label = "orders"
        indexes = [models.Index(fields=["order", "tier"], name="orderitem_order_tier_idx")]
        constraints = [models.CheckConstraint(check=models.Q(quantity__gte=0),name="orderitem_quantity_non_negative")]
    
    def __str__(self) -> str:
        return f"{self.quantity} x tier {self.tier_id} in Order {self.order_id}"
    
    @property
    def subtotal(self):
        return self.unit_price * self.quantity
    
    
def generate_qr_code() -> str:
    import uuid
    return uuid.uuid4().hex


# ---- Ticket ----
class Ticket(BaseModel):
    order_item = models.ForeignKey(OrderItem,on_delete=models.CASCADE,related_name="tickets")
    attendee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="tickets")
    event = models.ForeignKey("events.Event",on_delete=models.PROTECT,related_name="tickets")
    tier = models.ForeignKey("events.TicketTier",on_delete=models.PROTECT,related_name="tickets")
    status = models.CharField(max_length=20,choices=TicketStatus.choices,default=TicketStatus.VALID,db_index=True)
    qr_code = models.CharField(max_length=64,unique=True,default=generate_qr_code,help_text="Unique token for QR code generation. UUIDv4 hex.")
    checked_in_at = models.DateTimeField(null=True,blank=True,help_text="Set when ticket is scanned at event entry (Phase 5).")

    class Meta:
        app_label = "orders"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["event", "status"], name="ticket_event_status_idx"),
            models.Index(fields=["attendee", "status"], name="ticket_attendee_status_idx"),
            models.Index(fields=["qr_code"], name="ticket_qr_code_idx"),
            ]
    
    def __str__(self) -> str:
        return f"Ticket {self.qr_code[:8]}-({self.status})"