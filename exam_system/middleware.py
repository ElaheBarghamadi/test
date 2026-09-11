# -*- coding: utf-8 -*-
"""میان‌افزارهای امنیتی سفارشی"""


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
