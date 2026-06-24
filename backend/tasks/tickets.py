import logging

from celery import shared_task

from services.storage import build_ticket_pdf_key, upload_bytes
from services.ticket import render_ticket_pdf

logger = logging.getLogger(__name__)

@shared_task(bind=True,autoretry_for=(Exception,),retry_backoff_max=600,retry_jitter=True,max_retries=5,name="tasks.tickets.generate_ticket_assets_task")
def generate_ticket_assets_task(self, ticket_id):
    from apps.orders.models import Ticket

    ticket = (Ticket.objects.select_related("event", "event__org", "tier", "order_item").get(id=ticket_id))

    if ticket.pdf_url:
        logger.info("generate_ticket_assets_task: ticket %s already has a PDF, skipping", ticket_id)
        return ticket.pdf_url
    
    order = ticket.order_item.order
    pdf_bytes = render_ticket_pdf(
        qr_payload=ticket.qr_code,
        event_title=ticket.event.title,
        event_starts_at=ticket.event.start_datetime,
        venue=getattr(ticket.event, "venue", ""),
        attendee_name=ticket.attendee_name,
        tier_name=ticket.tier.name,
        order_reference=order.reference
    )

    key = build_ticket_pdf_key(
        org_slug=ticket.event.org.slug,
        event_slug=ticket.event.slug,
        ticket_id=ticket.id
    )
    upload_bytes(key=key, data=pdf_bytes, content_type="applications/pdf")

    ticket.pdf_url = key
    ticket.save(update_fields=["pdf_url", "updated_at"])

    from tasks.notifications import send_ticket_confirmation_email_task
    send_ticket_confirmation_email_task.delay(str(ticket_id))
    return key