"""
WSGI config for exam_system project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "exam_system.settings")

application = get_wsgi_application()


# 🚀 هنگام بالا آمدن سرور تولید (gunicorn/uwsgi): مایگریشن‌ها اعمال و کاربران پیش‌فرض ساخته می‌شوند.
# روی هاست‌هایی مثل Render که دیسک با هر deploy پاک می‌شود، بدون این کار کاربری وجود ندارد.
def _bootstrap():
    try:
        from django.core.management import call_command
        call_command('migrate', interactive=False, verbosity=0)   # post_migrate کاربران را می‌سازد
        call_command('ensure_default_users', verbosity=0)
    except Exception as exc:   # اگر چند worker هم‌زمان اجرا کنند، یکی موفق می‌شود
        print('⚠️ bootstrap:', exc)


_bootstrap()
