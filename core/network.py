"""Network helpers with explicit trusted-proxy handling."""
import ipaddress
from django.conf import settings


def client_ip(request):
    """Return a validated client IP.

    X-Forwarded-For is trusted only when TRUSTED_PROXY_COUNT is configured.
    With the default value 0, user-controlled forwarding headers are ignored.
    """
    remote = (request.META.get('REMOTE_ADDR') or '').strip()
    count = max(0, int(getattr(settings, 'TRUSTED_PROXY_COUNT', 0) or 0))
    forwarded = [x.strip() for x in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if x.strip()]
    candidate = forwarded[-count] if count and len(forwarded) >= count else remote
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None
