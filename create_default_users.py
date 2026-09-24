#!/usr/bin/env python
"""اسکریپت مستقل: python create_default_users.py
مایگریشن‌ها را اعمال می‌کند و کاربران admin/teacher/student را (اگر نباشند) می‌سازد."""
import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_system.settings')
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False, verbosity=0)
    call_command('ensure_default_users')
