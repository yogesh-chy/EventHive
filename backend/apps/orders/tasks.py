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