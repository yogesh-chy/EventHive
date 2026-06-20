"""
apps/orders/tasks.py  ·  PHASE 3

Celery tasks for the orders app.

PREDICTED PROBLEMS ADDRESSED:
  1. Expired PENDING orders never cleaned up → expire_pending_orders_task
     runs every 2 minutes via Celery Beat and calls
     services.expire_pending_orders().
  2. Two Celery workers processing the same expired order simultaneously →
     services.expire_pending_orders() uses select_for_update(skip_locked=True)
     so each order row is processed by exactly one worker.
  3. Task failure leaving all orders unprocessed → each order is wrapped
     in its own try/except inside the service; one failure does not block
     the remaining expired orders from being processed.
  4. Hard Celery dependency before Phase 5 → @shared_task decorator is
     commented out so the orders app installs without celery in the
     dependencies. Uncomment when Celery is added in Phase 5.

To activate as a real Celery task (Phase 5):
  1. pip install "celery[beat]>=5.3" django-celery-beat redis
  2. Uncomment the @shared_task decorator below.
  3. Add to settings:
       CELERY_BEAT_SCHEDULE = {
           "expire-pending-orders": {
               "task":     "apps.orders.tasks.expire_pending_orders_task",
               "schedule": 120,
           },
       }
"""

import logging

logger = logging.getLogger(__name__)


# Uncomment in Phase 5 when Celery is installed:
# from celery import shared_task
# @shared_task(name="apps.orders.tasks.expire_pending_orders_task")
def expire_pending_orders_task():
    """
    Cancel PENDING orders whose expires_at has passed and restore their inventory.
    Callable directly (no running worker needed) — useful in management commands
    and tests.
    """
    from .services import expire_pending_orders
    count = expire_pending_orders()
    logger.info("expire_pending_orders_task completed. cancelled=%d", count)
    return count
