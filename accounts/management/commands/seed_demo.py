# -*- coding: utf-8 -*-
"""ساخت داده نمونه برای آشنایی و تست سامانه

    python manage.py seed_demo

کاربرها (رمز همه: test12345):
    admin_t (مدیر) · teacher_t (معلم) · student_t1..t3 (دانش‌آموز پایه ۹) · student_t8 (پایه ۸)
و دو آزمون کامل با همه انواع سوال:
    ۱) صفحه‌به‌صفحه + ضدتقلب + تایمر شناور
    ۲) یکجا + تایمر ثابت + بدون ضدتقلب
"""
import json
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Grade
from exams.models import Exam, Question, StudentAnswer, ExamAttempt

User = get_user_model()


class Command(BaseCommand):
    help = 'ساخت کاربران و آزمون‌های نمونه (بی‌خطر و تکرارپذیر)'

    def handle(self, *args, **options):
        now = timezone.now()

        # ---------- پایه‌ها ----------
        grades = {}
        for code, _ in Grade.GRADE_CHOICES:
            grades[code], _ = Grade.objects.get_or_create(name=code)

        # ---------- کاربرها ----------
        def mkuser(username, role, grade=None, code=None, first='', last=''):
            u, _ = User.objects.get_or_create(
                username=username,
                defaults=dict(role=role, grade=grade, student_code=code,
                              first_name=first, last_name=last,
                              email=f'{username}@test.local'))
            u.set_password('test12345')
            u.role, u.grade, u.student_code = role, grade, code
            u.first_name = first or u.first_name
            u.last_name = last or u.last_name
            if role == 'admin':
                u.is_staff = u.is_superuser = True
            u.save()
            return u

        mkuser('admin_t', 'admin', first='مدیر', last='سیستم')
        teacher = mkuser('teacher_t', 'teacher', first='مریم', last='احمدی')
        students = [
            mkuser('student_t1', 'student', grade=grades['9'], code='140312001', first='زهرا', last='محمدی'),
            mkuser('student_t2', 'student', grade=grades['9'], code='140312002', first='رضا', last='کریمی'),
            mkuser('student_t3', 'student', grade=grades['9'], code='140312003', first='سارا', last='حسینی'),
        ]

        # ---------- تصویرهای نمونه ----------
        img_dir = os.path.join(settings.MEDIA_ROOT, 'question_images')
        os.makedirs(img_dir, exist_ok=True)

        def make_image(name, text, color):
            try:
                from PIL import Image, ImageDraw
            except ImportError:
                return None
            path = os.path.join(img_dir, name)
            if not os.path.exists(path):
                img = Image.new('RGB', (640, 360), color)
                d = ImageDraw.Draw(img)
                d.rectangle([8, 8, 631, 351], outline='white', width=4)
                d.text((40, 160), text, fill='white')
                img.save(path)
            return f'question_images/{name}'

        rel_geo = make_image('demo_geo.png', 'Naghshe Iran', (52, 96, 140))
        opt_imgs = [make_image(f'demo_opt{i}.png', f'Option {i}', c)
                    for i, c in enumerate([(140, 60, 60), (60, 120, 70), (120, 90, 40), (80, 60, 130)], 1)]
        opt_imgs = [p for p in opt_imgs if p]

        # ---------- آزمون‌ها ----------
        def get_exam(title, **kw):
            e, _ = Exam.objects.get_or_create(
                title=title, teacher=teacher,
                defaults=dict(grade=grades['9'], duration_minutes=30,
                              start_time=now - timedelta(minutes=10),
                              end_time=now + timedelta(hours=6)))
            for k, v in kw.items():
                setattr(e, k, v)
            e.start_time = now - timedelta(minutes=10)
            e.grade = grades['9']
            e.save()
            e.students.set(students)
            return e

        exam_page = get_exam(
            'آزمون جامع — صفحه به صفحه',
            duration_minutes=25, show_questions_mode='one_by_one', show_back_button=True,
            enable_anti_cheat=True, prevent_tab_switch=True, prevent_copy_paste=True,
            track_ip=True, random_questions=False, timer_type='floating',
            show_score_to_student=True, show_answers_after_exam=True)
        exam_all = get_exam(
            'آزمون جامع — یکجا',
            duration_minutes=40, show_questions_mode='all', show_back_button=False,
            enable_anti_cheat=False, prevent_tab_switch=False, prevent_copy_paste=False,
            track_ip=False, random_questions=True, timer_type='fixed',
            end_time=now + timedelta(hours=2),
            show_score_to_student=True, show_answers_after_exam=False)

        def build_questions(exam):
            exam.questions.all().delete()
            specs = [
                dict(question_type='true_false',
                     text='پایتخت کشور ایران، شهر تهران است.',
                     max_score=Decimal('1'), correct_answer='true'),
                dict(question_type='multiple_choice', options_type='text',
                     text='کدام یک از موارد زیر از خواص آب است؟\n(فقط یک گزینه را انتخاب کنید)',
                     options=['رسانای خوب الکتریسیته', 'بی‌رنگ و بی‌بو', 'سنگین‌تر از جیوه', 'در دمای اتاق جامد'],
                     max_score=Decimal('2'), correct_answer='2'),
                dict(question_type='fill_blank',
                     text='جاهای خالی را کامل کنید:\n۱) بزرگ‌ترین سیاره منظومه شمسی ______ است.\n'
                          '۲) نماد شیمیایی آب ______ است.\n۳) بلندترین قله ایران ______ نام دارد.',
                     blanks=['بزرگ‌ترین سیاره', 'نماد شیمیایی آب', 'بلندترین قله ایران'],
                     max_score=Decimal('3'), correct_answer='مشتری, H2O, دماوند'),
                dict(question_type='short_answer',
                     text='با ذکر یک مثال، تعریف کوتاهی از «چگالی» بنویسید.',
                     max_score=Decimal('2'), correct_answer='جرم تقسیم بر حجم'),
                dict(question_type='long_answer',
                     text='درباره نقش آب در زندگی انسان و راه‌های صرفه‌جویی در مصرف آن، '
                          'یک پاسخ تشریحی کامل بنویسید.',
                     max_score=Decimal('4'), correct_answer='پاسخ تشریحی دانش‌آموز'),
                dict(question_type='image_answer',
                     text='حل مسئله زیر را روی کاغذ بنویسید و تصویر آن را آپلود کنید:\n'
                          '«محیط مستطیلی به طول ۸ و عرض ۵ سانتی‌متر را حساب کنید.»',
                     max_score=Decimal('3'), allow_image_answer=True),
                dict(question_type='matching',
                     text='هر کشور را به پایتخت آن وصل کنید.',
                     matching_pairs=[{'left': 'ایران', 'right': 'تهران'},
                                     {'left': 'فرانسه', 'right': 'پاریس'},
                                     {'left': 'ژاپن', 'right': 'توکیو'},
                                     {'left': 'مصر', 'right': 'قاهره'},
                                     {'left': 'برزیل', 'right': 'برازیلیا'}],
                     max_score=Decimal('5')),
            ]
            if rel_geo and opt_imgs:
                specs.insert(2, dict(
                    question_type='multiple_choice', options_type='image',
                    text='تصویر مربوط به کدام گزینه است؟ (گزینه‌ها تصویری هستند)',
                    options=['/media/' + p for p in opt_imgs],
                    max_score=Decimal('2'), correct_answer='1'))
                specs.append(dict(
                    question_type='short_answer', image=rel_geo,
                    text='با توجه به تصویر زیر، نام دو استان همسایه را بنویسید.',
                    max_score=Decimal('2'), allow_image_answer=True))

            created = []
            for i, spec in enumerate(specs, start=1):
                spec = dict(spec)
                img = spec.pop('image', None)
                q = Question.objects.create(exam=exam, order=i, text=spec.pop('text'), **spec)
                if img:
                    q.image.name = img
                    q.save()
                if q.question_type == 'matching':
                    q.correct_answer = json.dumps(
                        {f'pair_{q.id}_{i2}': f'r_{i2}' for i2 in range(len(q.matching_pairs))},
                        ensure_ascii=False)
                    q.save()
                created.append(q)
            return created

        qs_page = build_questions(exam_page)
        build_questions(exam_all)

        # چند پاسخ ذخیره‌شده برای دیدن وضعیت «ادامه آزمون»
        if qs_page:
            StudentAnswer.objects.update_or_create(
                student=students[0], question=qs_page[1], defaults={'answer_text': '2'})
            StudentAnswer.objects.update_or_create(
                student=students[0], question=qs_page[4],
                defaults={'answer_text': 'مشتری |  | دماوند'})
        ExamAttempt.objects.filter(student=students[0], exam=exam_all).delete()

        self.stdout.write(self.style.SUCCESS('داده نمونه آماده شد:'))
        self.stdout.write(f'  ۱) {exam_page.title} → {exam_page.questions.count()} سوال | صفحه‌به‌صفحه | ضدتقلب')
        self.stdout.write(f'  ۲) {exam_all.title} → {exam_all.questions.count()} سوال | یکجا')
        self.stdout.write('  ورود: admin_t / teacher_t / student_t1 — رمز: test12345')
