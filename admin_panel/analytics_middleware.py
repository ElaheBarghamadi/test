import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone


class SiteAnalyticsMiddleware:
    """ثبت سبک درخواست‌های واقعی برای گزارش مرکز کنترل (نگهداری ۳۶۵ روز)."""
    SKIP_PREFIXES = ('/static/', '/media/', '/favicon.ico')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        if request.path.startswith(self.SKIP_PREFIXES):
            return response
        try:
            from .models import SiteVisit, client_ip, parse_user_agent
            ua = request.META.get('HTTP_USER_AGENT', '')[:500]
            parsed = parse_user_agent(ua)
            SiteVisit.objects.create(
                user=request.user if getattr(request, 'user', None) and request.user.is_authenticated else None,
                path=request.path[:500], method=request.method[:8], status_code=response.status_code,
                response_ms=min(int((time.perf_counter() - started) * 1000), 2147483647),
                ip_address=client_ip(request), user_agent=ua, browser=parsed['browser'][:60],
                os=parsed['os'][:60], device=parsed['device'][:30],
                referrer=request.META.get('HTTP_REFERER', '')[:500],
            )
            # پاک‌سازی حداکثر روزی یک‌بار، نه در هر درخواست
            if cache.add('analytics:retention-cleanup', True, 86400):
                SiteVisit.objects.filter(created_at__lt=timezone.now()-timedelta(days=365)).delete()
        except Exception:
            pass
        return response
