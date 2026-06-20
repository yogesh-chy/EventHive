"""
apps/orders/migrations/0002_phase3_payments.py

Re-aligns the orders schema to the EventHive_Architecture.pdf blueprint:
  - Order.reference, idempotency_key, confirmed_at, cancelled_at  (new)
  - Order.payment_intent_id renamed → stripe_payment_intent_id, now unique+nullable
  - Ticket.attendee_name, attendee_email, pdf_url  (new)
  - ProcessedStripeEvent  (new model — idempotent webhook ledger)

PREDICTED PROBLEMS ADDRESSED:
  1. Adding a unique=True field to a table that already has rows → cannot
     add unique=True directly if existing rows would collide. Sequence used:
       a) AddField reference as nullable/blank, no unique yet
       b) RunPython: backfill a real generated reference for every existing row
       c) AlterField: enforce unique=True + db_index=True only after backfill
  2. Renaming payment_intent_id → stripe_payment_intent_id while changing
     blank="" semantics to null=True → existing empty-string values must be
     converted to NULL first, otherwise multiple empty strings would violate
     the new unique constraint (Postgres treats '' as a normal duplicable
     value, but NULL is not subject to uniqueness). RunPython handles this.
  3. idempotency_key backfill is optional (nullable, multiple NULLs allowed)
     but included anyway so existing pre-payment orders get a key ready for
     when they're confirmed/refunded later.
  4. Migration must be reversible — reverse_code provided for every
     RunPython step; reversing a one-way data backfill is not meaningful,
     so those reverse functions are deliberate no-ops (documented, not
     silently broken).
"""

import uuid

from django.db import migrations, models


# ── Data migration: backfill reference ────────────────────────────────────────

def backfill_order_references(apps, schema_editor):
    import secrets

    Order = apps.get_model("orders", "Order")
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

    existing_refs = set(
        Order.objects.exclude(reference="").values_list("reference", flat=True)
    )

    for order in Order.objects.filter(reference="").iterator():
        for _ in range(50):
            candidate = "".join(secrets.choice(alphabet) for _ in range(8))
            if candidate not in existing_refs:
                existing_refs.add(candidate)
                order.reference = candidate
                order.save(update_fields=["reference"])
                break


def noop_reverse(apps, schema_editor):
    # Reversing a reference backfill has no meaningful action — references
    # are public-facing values that should not be unset once assigned, even
    # when rolling back this migration's schema changes.
    pass


# ── Data migration: convert blank payment_intent_id to NULL ──────────────────

def blank_payment_intent_to_null(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(payment_intent_id="").update(payment_intent_id=None)


def null_payment_intent_to_blank(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(payment_intent_id__isnull=True).update(payment_intent_id="")


# ── Data migration: generate idempotency keys for existing rows ──────────────

def backfill_idempotency_keys(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    for order in Order.objects.filter(idempotency_key__isnull=True).iterator():
        order.idempotency_key = uuid.uuid4().hex
        order.save(update_fields=["idempotency_key"])


def noop_reverse_idempotency(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [

        # ── Order: add new fields (nullable / blank first) ───────────────────
        migrations.AddField(
            model_name="order",
            name="reference",
            field=models.CharField(max_length=8, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="order",
            name="idempotency_key",
            field=models.CharField(max_length=64, null=True, blank=True, default=None),
        ),
        migrations.AddField(
            model_name="order",
            name="confirmed_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="order",
            name="cancelled_at",
            field=models.DateTimeField(null=True, blank=True),
        ),

        # ── Backfill data BEFORE enforcing constraints ────────────────────────
        migrations.RunPython(backfill_order_references, reverse_code=noop_reverse),
        migrations.RunPython(blank_payment_intent_to_null, reverse_code=null_payment_intent_to_blank),
        migrations.RunPython(backfill_idempotency_keys, reverse_code=noop_reverse_idempotency),

        # ── Now enforce uniqueness / rename ────────────────────────────────────
        migrations.AlterField(
            model_name="order",
            name="reference",
            field=models.CharField(max_length=8, unique=True, db_index=True),
        ),
        migrations.AlterField(
            model_name="order",
            name="idempotency_key",
            field=models.CharField(max_length=64, unique=True, null=True, blank=True, default=None),
        ),
        migrations.RenameField(
            model_name="order",
            old_name="payment_intent_id",
            new_name="stripe_payment_intent_id",
        ),
        migrations.AlterField(
            model_name="order",
            name="stripe_payment_intent_id",
            field=models.CharField(
                max_length=255, unique=True, null=True, blank=True, default=None, db_index=True,
            ),
        ),

        # ── Ticket: add Payments-related fields ────────────────────────────────
        migrations.AddField(
            model_name="ticket",
            name="attendee_name",
            field=models.CharField(max_length=255, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="ticket",
            name="attendee_email",
            field=models.EmailField(max_length=254, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="ticket",
            name="pdf_url",
            field=models.CharField(max_length=500, blank=True, default=""),
        ),

        # ── ProcessedStripeEvent: idempotent webhook ledger ────────────────────
        migrations.CreateModel(
            name="ProcessedStripeEvent",
            fields=[
                ("id",              models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ("stripe_event_id", models.CharField(max_length=255, unique=True, db_index=True)),
                ("event_type",      models.CharField(max_length=100)),
                ("processed_at",    models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-processed_at"], "app_label": "orders"},
        ),
    ]
