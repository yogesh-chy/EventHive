"""
Phase 4: regression test for the exact bug this phase's task-routing fix
caught -- Celery's actual default queue is named "celery", not "default".
Without CELERY_TASK_DEFAULT_QUEUE set, the Beat dispatcher tasks and
expire_pending_orders_task would silently route to a queue no worker
started with `-Q default,assets,emails` is listening on.
"""
import pytest

from config.celery import app


@pytest.mark.parametrize(
    "task_name,expected_queue",
    [
        ("tasks.tickets.generate_ticket_assets_task", "assets"),
        ("tasks.notifications.send_ticket_confirmation_email_task", "emails"),
        ("tasks.notifications.send_event_reminder_email_task", "emails"),
        ("tasks.notifications.send_abandoned_cart_email_task", "emails"),
        ("tasks.notifications.dispatch_event_reminders_task", "default"),
        ("tasks.notifications.dispatch_abandoned_cart_emails_task", "default"),
        ("apps.orders.tasks.expire_pending_orders_task", "default"),
    ],
)
def test_task_routes_to_expected_queue(task_name, expected_queue):
    app.loader.import_default_modules()
    route = app.amqp.router.route({}, task_name)
    assert route["queue"].name == expected_queue
