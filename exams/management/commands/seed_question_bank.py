"""
ساخت بانک سوال نمونهٔ کامل و پوشه‌بندی‌شده (پایه › درس › فصل) برای یک معلم.

    python manage.py seed_question_bank                 # برای معلم «teacher»
    python manage.py seed_question_bank --teacher ali   # برای معلم دیگر
    python manage.py seed_question_bank --all           # برای همهٔ معلم‌ها
    python manage.py seed_question_bank --reset         # اول بانک معلم پاک و بعد از نو ساخته شود

اجرای چندباره امن است؛ فقط پوشه‌ها و سوال‌های ناموجود اضافه می‌شوند.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from exams.bank_seed import seed_question_bank, iter_bank


class Command(BaseCommand):
    help = 'ساخت بانک سوال نمونهٔ پوشه‌بندی‌شده برای پنل معلم'

    def add_arguments(self, parser):
        parser.add_argument('--teacher', default='teacher', help='نام کاربری معلم (پیش‌فرض: teacher)')
        parser.add_argument('--all', action='store_true', help='برای همهٔ معلم‌ها')
        parser.add_argument('--reset', action='store_true', help='حذف بانک و پوشه‌های فعلی معلم پیش از ساخت')

    def handle(self, *args, **opts):
        if opts['all']:
            teachers = list(User.objects.filter(role='teacher'))
        else:
            if opts['teacher'] == 'teacher' and not User.objects.filter(username='teacher').exists():
                call_command('ensure_default_users')
            teachers = list(User.objects.filter(username=opts['teacher'], role='teacher'))
        if not teachers:
            raise CommandError('معلمی با این مشخصات پیدا نشد.')

        total = sum(1 for _ in iter_bank())
        for t in teachers:
            if opts['reset']:
                t.bank_questions.all().delete()
                t.bank_folders.all().delete()
            nf, nq = seed_question_bank(t)
            self.stdout.write(self.style.SUCCESS(
                f'✓ {t.username}: {nf} پوشهٔ جدید، {nq} سوال جدید (از {total} سوال بانک نمونه)'))
