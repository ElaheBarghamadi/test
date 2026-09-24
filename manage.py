#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def apply_pending_migrations():
    """در حالت توسعه (runserver) مایگریشن‌های مانده خودکار اعمال می‌شوند.

    تا پس از کشیدن کد جدید، فراموش‌کردن `manage.py migrate` باعث خطای
    «no such table» نشود. در تولید (gunicorn و…) این کد اجرا نمی‌شود.
    """
    try:
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor
        conn = connections['default']
        executor = MigrationExecutor(conn)
        targets = executor.loader.graph.leaf_nodes()
        if executor.migration_plan(targets):
            print('⏳ اعمال مایگریشن‌های باقی‌مانده…', flush=True)
            call_command('migrate', interactive=False, verbosity=1)
            print('✅ مایگریشن‌ها اعمال شد.', flush=True)
    except Exception as exc:  # هر مشکلی نباید جلوی بالا آمدن سرور را بگیرد
        print(f'⚠️ بررسی مایگریشن ناموفق بود (نیاز به اجرای دستی migrate): {exc}', flush=True)


def ensure_default_users():
    """هر بار اجرای runserver: کاربران admin/teacher/student اگر نباشند ساخته می‌شوند."""
    try:
        from django.core.management import call_command
        call_command('ensure_default_users')
        sys.stdout.flush()
    except Exception as exc:
        print(f'⚠️ ساخت کاربران پیش‌فرض ناموفق بود: {exc}', flush=True)


def main():
    """Run administrative commands."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "exam_system.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # فقط در فرایند اصلی runserver (نه فرایند autoreload) تا دوبار اجرا نشود
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver' and os.environ.get('RUN_MAIN') != 'true':
        apply_pending_migrations()
        ensure_default_users()
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
