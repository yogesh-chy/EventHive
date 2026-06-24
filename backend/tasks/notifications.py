import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

_RETRY_KWARGS = dict(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5
)

def send_templated_email(*, to_email: str, subject: str, template_base: str, context: dict) -> None:
    text_body = render_to_string(f"{template_base}.txt", context)
    message = EmailMultiAlternatives(subject=subject, body=text_body, to=[to_email])
    
    try:
        html_body = render_to_string(f"{template_base}.html", context)
        message.attach_alternative(html_body, "text/html")
    except Exception:
        pass
    message.send(fail_silently=False)

@shared_task(name="tasks.notifications.send_ticket_confirmation_email_task", **_RETRY_KWARGS)
def send_ticket_confirmation_email_task(self, ticket_id):
    from apps.notifications.models import NotificationLog
    from apps.orders.models import Ticket
    from services.storage import generate_presigned_url

    ticket = Ticket.objects.select_related("event", "order_item__order").get(id=ticket_id)
    order = ticket.order_item.order

    log, _created = NotificationLog.claim(
        notification_type=NotificationLog.NotificationType.TICKET_CONFIRMATION,
        target_type="tickets",
        target_id=ticket.id,
        recipient_email=ticket.attendee_email
    )
    if log.status == NotificationLog.Status.SENT:
        return
    
    try:
        pdf_url = generate_presigned_url(
            key=ticket.pdf_url, expires_in=settings.TICKET_PDF_LINK_TTL_SECONDS
        )
        send_templated_email(
            to_email=ticket.attendee_email,
            subject=f"Your ticket for {ticket.event.title}",
            template_base="notifications/emails/ticket_confirmation",
            context={
                "attendee_name": ticket.attendee_name,
                "event": ticket.event,
                "order": order,
                "pdf_url": pdf_url,
            },
        )
    except Exception as exc:
        log.mark_failed(str(exc))
        raise # re-raise so Celery's autoretry_for actually retries

    log.mark_sent()

@shared_task(name="tasks.notifications.dispatch_event_reminders_task")
def dispatch_event_reminders_task():
    from apps.events.models import Event
    from apps.orders.models import Ticket, TicketStatus

    now = timezone.now()
    cutoff = now + timedelta(hours=24, minutes=15)

    tickets = Ticket.objects.filter(
        event__start_datetime__gte=now,
        event__start_datetime__lte=cutoff,
        status=TicketStatus.VALID,
        order_item__order__status="CONFIRMED"
    )
    for ticket in tickets:
        send_event_reminder_email_task.delay(str(ticket.id))

@shared_task(name="tasks.notifications.send_event_reminder_email_task", **_RETRY_KWARGS)
def send_event_reminder_email_task(self, ticket_id):
    from apps.notifications.models import NotificationLog
    from apps.orders.models import Ticket

    ticket = Ticket.objects.select_related("event").get(id=ticket_id)

    log, _created = NotificationLog.claim(
        notification_type=NotificationLog.NotificationType.EVENT_REMINDER,
        target_type="ticket",
        target_id=ticket.id,
        recipient_email=ticket.attendee_email
    )
    if log.status == NotificationLog.Status.SENT:
        return
    
    try:
        send_templated_email(
            to_email=ticket.attendee_email,
            subject=f"Reminder: {ticket.event.title} is tomorrow!",
            template_base="notifications/emails/event_reminder",
            context={
                "attendee_name": ticket.attendee_name,
                "event": ticket.event,
            },
        )
    except Exception as exc:
        log.mark_failed(str(exc))
        raise

    log.mark_sent()

@shared_task(name="tasks.notifications.dispatch_abandoned_cart_emails_task")
def dispatch_abandoned_cart_emails_task():
    from apps.orders.models import Order, OrderStatus
    from apps.orders.services import ORDER_EXPIRY_MINUTES

    abandoned_after = timezone.now() - timedelta(minutes=settings.ABANDONED_CART_AFTER_MINUTES)
    expiry_cutoff = timezone.now() - timedelta(minutes=ORDER_EXPIRY_MINUTES)

    orders = Order.objects.filter(
        status=OrderStatus.PENDING,
        created_at__lte=abandoned_after,
        created_at__gt=expiry_cutoff
    )
    for order in orders:
        send_abandoned_cart_email_task.delay(str(order.id))

@shared_task(name="tasks.notifications.send_abandoned_cart_email_task", **_RETRY_KWARGS)
def send_abandoned_cart_email_task(self, order_id):
    from apps.notifications.models import NotificationLog
    from apps.orders.models import Order

    order = Order.objects.select_related("event", "attendee").get(id=order_id)
    recipient = order.attendee.email

    log, _created = NotificationLog.claim(
        notification_type=NotificationLog.NotificationType.ABANDONED_CART,
        target_type="order",
        target_id=order.id,
        recipient_email=recipient
    )
    if log.status == NotificationLog.Status.SENT:
        return
    
    try:
        send_templated_email(
            to_email=recipient,
            subject=f"Still want your tickets to {order.event.title}?",
            template_base="notifications/emails/abandoned_cart",
            context={"order": order, "event": order.event},
        )
    except Exception as exc:
        log.mark_failed(str(exc))
        raise

    log.mark_sent()