import time
import logging

logger = logging.getLogger(__name__)

class AuditLogMiddleware:
    """
    Middleware to log requests and inject audit information.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Pre-processing: Record start time
        start_time = time.time()

        # 2. Process the request
        response = self.get_response(request)

        # 3. Post-processing: Calculate duration and log
        duration = time.time() - start_time
        
        # Log basic request info (expand this later for your AuditLog model)
        user = request.user if request.user.is_authenticated else "Anonymous"
        logger.info(
            f"User: {user} | Method: {request.method} | Path: {request.path} | "
            f"Status: {response.status_code} | Duration: {duration:.2f}s"
        )

        return response
