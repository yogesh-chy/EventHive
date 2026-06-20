"""
apps/orders/migrations/0001_initial.py  ·  PHASE 3

Creates Order, OrderItem, Ticket tables with all indexes and constraints.

Migration dependencies:
  - events 0002 (Event + TicketTier tables must already exist)
  - AUTH_USER_MODEL (users app migration must already exist)

Run in this order:
  python manage.py migrate users
  python manage.py migrate organizations
  python manage.py migrate events
  python manage.py migrate orders   ← this file

PREDICTED PROBLEMS ADDRESSED:
  1. on_delete=PROTECT → enforced at DB level; deleting a User or Event
     that has orders raises IntegrityError before any row is touched.
  2. CheckConstraints on quantity and unit_price → DB-level defence
     in addition to serializer validation (two layers).
  3. qr_code unique constraint → collision caught at DB level even if
     application code fails to generate a unique value.
  4. Composite index on (status, expires_at) → required for the Celery
     expiry query: WHERE status='PENDING' AND expires_at < now().
"""

import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0002_add_search_vector_trigger"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── Order ──────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id",                models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("created_at",        models.DateTimeField(auto_now_add=True)),
                ("updated_at",        models.DateTimeField(auto_now=True)),
                ("is_deleted",        models.BooleanField(default=False, db_index=True)),
                ("attendee",          models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="orders",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("event",             models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="orders",
                    to="events.event",
                )),
                ("created_by",        models.ForeignKey(
                    null=True, blank=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("status",            models.CharField(
                    max_length=20, db_index=True, default="PENDING",
                    choices=[
                        ("PENDING",   "Pending"),
                        ("CONFIRMED", "Confirmed"),
                        ("CANCELLED", "Cancelled"),
                        ("REFUNDED",  "Refunded"),
                    ],
                )),
                ("total_amount",      models.DecimalField(max_digits=12, decimal_places=2)),
                ("currency",          models.CharField(max_length=3, default="USD")),
                ("payment_intent_id", models.CharField(max_length=255, blank=True, default="", db_index=True)),
                ("expires_at",        models.DateTimeField(null=True, blank=True, db_index=True)),
            ],
            options={"ordering": ["-created_at"], "app_label": "orders"},
        ),
        migrations.AddIndex(model_name="order",
            index=models.Index(fields=["attendee", "status"],   name="order_attendee_status_idx")),
        migrations.AddIndex(model_name="order",
            index=models.Index(fields=["event",    "status"],   name="order_event_status_idx")),
        migrations.AddIndex(model_name="order",
            index=models.Index(fields=["status",   "expires_at"], name="order_status_expires_idx")),

        # ── OrderItem ──────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id",         models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False, db_index=True)),
                ("order",      models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="items",
                    to="orders.order",
                )),
                ("tier",       models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="order_items",
                    to="events.tickettier",
                )),
                ("quantity",   models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(max_digits=10, decimal_places=2)),
            ],
            options={"app_label": "orders"},
        ),
        migrations.AddIndex(model_name="orderitem",
            index=models.Index(fields=["order", "tier"], name="orderitem_order_tier_idx")),
        migrations.AddConstraint(model_name="orderitem",
            constraint=models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="orderitem_quantity_positive",
            )),
        migrations.AddConstraint(model_name="orderitem",
            constraint=models.CheckConstraint(
                check=models.Q(unit_price__gte=0),
                name="orderitem_price_non_negative",
            )),

        # ── Ticket ─────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name="Ticket",
            fields=[
                ("id",            models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("created_at",    models.DateTimeField(auto_now_add=True)),
                ("updated_at",    models.DateTimeField(auto_now=True)),
                ("is_deleted",    models.BooleanField(default=False, db_index=True)),
                ("order_item",    models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="tickets",
                    to="orders.orderitem",
                )),
                ("attendee",      models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="tickets",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("event",         models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="tickets",
                    to="events.event",
                )),
                ("tier",          models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="tickets",
                    to="events.tickettier",
                )),
                ("status",        models.CharField(
                    max_length=20, db_index=True, default="VALID",
                    choices=[
                        ("VALID",     "Valid"),
                        ("USED",      "Used"),
                        ("CANCELLED", "Cancelled"),
                    ],
                )),
                ("qr_code",       models.CharField(max_length=64, unique=True)),
                ("checked_in_at", models.DateTimeField(null=True, blank=True)),
            ],
            options={"ordering": ["created_at"], "app_label": "orders"},
        ),
        migrations.AddIndex(model_name="ticket",
            index=models.Index(fields=["event",    "status"], name="ticket_event_status_idx")),
        migrations.AddIndex(model_name="ticket",
            index=models.Index(fields=["attendee", "status"], name="ticket_attendee_status_idx")),
        migrations.AddIndex(model_name="ticket",
            index=models.Index(fields=["qr_code"],            name="ticket_qr_code_idx")),
    ]
