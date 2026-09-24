import sys

from django.apps import AppConfig


def _ensure_default_users(sender, **kwargs):
    """بعد از هر migrate، کاربران پیش‌فرض (admin/teacher/student) ساخته می‌شوند اگر نباشند."""
    if 'test' in sys.argv:          # دیتابیس تست دست نخورد
        return
    from django.core.management import call_command
    try:
        call_command('ensure_default_users', verbosity=kwargs.get('verbosity', 1))
    except Exception as exc:        # نباید migrate را خراب کند
        print('⚠️ ساخت کاربران پیش‌فرض ناموفق بود:', exc)


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_ensure_default_users, sender=self, dispatch_uid='accounts_default_users')
