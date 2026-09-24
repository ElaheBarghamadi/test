"""
ساخت سه کاربر پیش‌فرض (ادمین اصلی، معلم، دانش‌آموز) — فقط اگر وجود نداشته باشند.
نام کاربری و رمز عبور هر کاربر یکی است:

    admin   / admin     (مدیر اصلی + superuser برای /admin/)
    teacher / teacher   (معلم)
    student / student   (دانش‌آموز، پایه هفتم)

اجرا:  python manage.py ensure_default_users
این دستور idempotent است؛ هر چند بار اجرا شود، کاربر تکراری نمی‌سازد و
به رمز کاربران موجود دست نمی‌زند.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Grade

DEFAULT_USERS = [
    dict(username='admin', role='admin', first_name='مدیر', last_name='اصلی',
         is_staff=True, is_superuser=True),
    dict(username='teacher', role='teacher', first_name='معلم', last_name='نمونه'),
    dict(username='student', role='student', first_name='دانش‌آموز', last_name='نمونه',
         grade='7', student_code='1000000001'),
]


class Command(BaseCommand):
    help = 'ساخت کاربران پیش‌فرض admin / teacher / student (رمز = نام کاربری) در صورت نبود'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        quiet = options.get('verbosity', 1) == 0
        for spec in DEFAULT_USERS:
            spec = dict(spec)
            username = spec.pop('username')
            if User.objects.filter(username=username).exists():
                if not quiet:
                    self.stdout.write(f'• {username}: از قبل وجود دارد')
                continue

            grade_name = spec.pop('grade', None)
            if grade_name:
                spec['grade'], _ = Grade.objects.get_or_create(name=grade_name)
            code = spec.get('student_code')
            if code and User.objects.filter(student_code=code).exists():
                spec.pop('student_code')  # جلوگیری از خطای یکتایی

            user = User(username=username, **spec)
            user.set_password(username)   # رمز = نام کاربری
            user.save()
            if not quiet:
                self.stdout.write(self.style.SUCCESS(f'✓ {username}: ساخته شد (رمز: {username})'))

        # بانک سوال شروع (~۲۰ سوال پوشه‌بندی‌شده) برای اکانت teacher، اگر بانکش خالی باشد
        try:
            from exams.bank_seed import STARTER_BANK, seed_question_bank
            from exams.models import BankFolder, QuestionBank
            teacher = User.objects.filter(username='teacher', role='teacher').first()
            if teacher and not QuestionBank.objects.filter(teacher=teacher).exists() \
                    and not BankFolder.objects.filter(teacher=teacher).exists():
                nf, nq = seed_question_bank(teacher, bank=STARTER_BANK)
                if not quiet:
                    self.stdout.write(self.style.SUCCESS(f'✓ بانک سوال teacher: {nq} سوال در {nf} پوشه'))
        except Exception as exc:
            self.stderr.write(f'⚠️ ساخت بانک سوال شروع ناموفق بود: {exc}')
