from rest_framework.throttling import SimpleRateThrottle

class TicketPurchaseThrottle(SimpleRateThrottle):
    """
    Limits ticket purchases (checkout) to 10/minute per authenticated user.
    """
    scope = "ticket_purchase"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            # Only throttle authenticated users for ticket purchases
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": str(request.user.pk),
        }


class PasswordResetEmailThrottle(SimpleRateThrottle):
    """
    Limits password reset request attempts to 5/hour per email address.
    Matches email address case-insensitively.
    """
    scope = "password_reset_email"

    def get_cache_key(self, request, view):
        email = request.data.get("email")
        if not email:
            # Fallback to IP address if email payload is not found/invalid
            return self.get_ident(request)
            
        email_normalized = str(email).strip().lower()
        return self.cache_format % {
            "scope": self.scope,
            "ident": email_normalized,
        }
