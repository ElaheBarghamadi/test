from django.core.cache import cache
from django.utils.deprecation import MiddlewareMixin
from django.http import Http404
from django.shortcuts import redirect, render


class SingleSessionMiddleware(MiddlewareMixin):
    """محدودیت همزمانی - فقط یک سشن فعال برای هر کاربر"""

    def process_request(self, request):
        # مسیرهایی که نباید چک شوند
        exclude_paths = ['/login/', '/logout/', '/admin/', '/favicon.ico', '/media/']

        for path in exclude_paths:
            if request.path.startswith(path):
                return None

        # اگر کاربر وارد نشده، کاری نکن
        if not request.user.is_authenticated:
            return None

        user_id = str(request.user.id)
        session_key = request.session.session_key

        if not session_key:
            return None

        # گرفتن سشن ذخیره شده از کش
        cached_session = cache.get(f'user_session_{user_id}')

        if cached_session and cached_session != session_key:
            # کاربر جای دیگری وارد شده، سشن فعلی را باطل کن
            request.session.flush()
            return redirect('login')
        else:
            # ذخیره سشن فعلی در کش
            cache.set(f'user_session_{user_id}', session_key, 86400)

        return None

class SecurityHeadersMiddleware:
    """افزودن هدرهای امنیتی پایه به همه پاسخ‌ها"""

    HEADERS = {
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
        'Cross-Origin-Opener-Policy': 'same-origin',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for key, value in self.HEADERS.items():
            response.setdefault(key, value)
        return response


class BrandedNotFoundMiddleware:
    """صفحه ۴۰۴ برندشده حتی در حالت DEBUG — بدون شکستن API های JSON"""

    def __init__(self, get_response):
        self.get_response = get_response

    def _wants_html(self, request):
        return (request.method == 'GET'
                and 'text/html' in request.headers.get('Accept', '')
                and not request.path.startswith(('/static/', '/media/', '/admin/')))

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Http404:
            if self._wants_html(request):
                return render(request, '404.html', status=404)
            raise
        if response.status_code == 404 and self._wants_html(request):
            return render(request, '404.html', status=404)
        return response
