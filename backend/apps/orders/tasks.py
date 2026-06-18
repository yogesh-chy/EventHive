import logging

logger = logging.getLogger(__name__)

# Uncomment in Phase 5 when Celery is installed:
# from celery import shared_task
# @shared_task(name="apps.orders.tasks.expire_pending_orders_task")
def expire_pending_orders_task():
    from .services import expire_pending_orders
    count = expire_pending_orders()
    logger.info("expire_pending_orders_task completed. Cancelled=%d", count)
    return count