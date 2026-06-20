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
