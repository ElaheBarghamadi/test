# -*- coding: utf-8 -*-
"""تست‌های لایهٔ امنیت و اعتبارسنجی ورودی‌ها (core.security)"""
import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, RequestFactory
from django.utils import timezone

from core.security import (clean_text, clean_int, clean_choice, clean_username,
                           clean_student_code, password_policy, safe_redirect_target,
                           csv_formula_guard, validate_image_upload, validate_sheet_upload,
                           rate_limit_hit, terminate_user_sessions)
from exams.models import Exam, Announcement
from accounts.models import Grade

User = get_user_model()


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (8, 8), (10, 120, 130)).save(buf, format='PNG')
    return buf.getvalue()


class _FakeFile:
    def __init__(self, name, data):
        self.name = name
        self.size = len(data)
        self._buf = io.BytesIO(data)

    def seek(self, *a):
        return self._buf.seek(*a)

    def tell(self):
        return self._buf.tell()

    def read(self, *a):
        return self._buf.read(*a)


class CleanTextTests(TestCase):
    def test_strips_control_and_zero_width(self):
        val, err = clean_text('سلام\u200b دنیا\x07', max_len=50)
        self.assertIsNone(err)
        self.assertEqual(val, 'سلام دنیا')

    def test_length_cap_with_message(self):
        val, err = clean_text('a' * 300, max_len=200, label='عنوان')
        self.assertIsNotNone(err)
        self.assertIn('۲۰', err.replace('200', '۲۰۰'))
        self.assertLessEqual(len(val), 200)

    def test_required(self):
        val, err = clean_text('   ', required=True, label='عنوان')
        self.assertEqual(val, '')
        self.assertIsNotNone(err)

    def test_newlines_preserved_when_allowed(self):
        val, err = clean_text('خط اول\r\nخط دوم', max_len=50)
        self.assertIsNone(err)
        self.assertEqual(val, 'خط اول\nخط دوم')


class IntChoiceTests(TestCase):
    def test_int_range(self):
        self.assertEqual(clean_int('7', 1, 10), (7, None))
        self.assertEqual(clean_int('abc', 1, 10, default=3), (3, 'عدد باید یک عدد باشد.'))
        self.assertEqual(clean_int('99', 1, 10, default=1)[1] is not None, True)

    def test_choice(self):
        self.assertEqual(clean_choice('teacher', ('student', 'teacher')), ('teacher', None))
        val, err = clean_choice('hacker', ('student', 'teacher'), default='student')
        self.assertEqual(val, 'student')
        self.assertIsNotNone(err)


class UsernamePasswordTests(TestCase):
    def test_username_rules(self):
        self.assertEqual(clean_username('ali.rezaei_1')[1], None)
        self.assertIsNotNone(clean_username('ali rezaei')[1])      # فاصله ممنوع
        self.assertIsNotNone(clean_username('ab')[1])              # خیلی کوتاه
        self.assertIsNotNone(clean_username('<script>')[1])       # کاراکتر خطرناک

    def test_student_code(self):
        self.assertEqual(clean_student_code('140312001')[1], None)
        self.assertIsNotNone(clean_student_code('کد!')[1])

    def test_password_policy(self):
        self.assertIsNone(password_policy('test12345'))
        self.assertIsNotNone(password_policy('short1'))           # کمتر از ۸
        self.assertIsNotNone(password_policy('abcdefgh'))         # بدون رقم
        self.assertIsNotNone(password_policy('12345678'))         # بدون حرف
        self.assertIsNotNone(password_policy('has space1'))       # فاصله


class RedirectAndFormulaTests(TestCase):
    def test_safe_redirect(self):
        self.assertEqual(safe_redirect_target('/teacher/dashboard/', '/'), '/teacher/dashboard/')
        self.assertEqual(safe_redirect_target('https://evil.com', '/'), '/')
        self.assertEqual(safe_redirect_target('//evil.com', '/'), '/')
        self.assertEqual(safe_redirect_target('/\\evil.com', '/'), '/')
        self.assertEqual(safe_redirect_target('', '/teacher/'), '/teacher/')

    def test_csv_formula_guard(self):
        self.assertEqual(csv_formula_guard('=CMD(x)'), "'=CMD(x)")
        self.assertEqual(csv_formula_guard('+1'), "'+1")
        self.assertEqual(csv_formula_guard('سلام'), 'سلام')


class UploadValidationTests(TestCase):
    def test_fake_image_rejected(self):
        f = _FakeFile('shell.png', b'<?php system($_GET["c"]); ?>')
        self.assertIsNotNone(validate_image_upload(f))

    def test_real_png_accepted(self):
        f = _FakeFile('ok.png', _png_bytes())
        self.assertIsNone(validate_image_upload(f))

    def test_wrong_extension_rejected(self):
        f = _FakeFile('ok.exe', _png_bytes())
        self.assertIsNotNone(validate_image_upload(f))

    def test_oversized_rejected(self):
        f = _FakeFile('big.png', b'\x00' * (6 * 1024 * 1024))
        self.assertIsNotNone(validate_image_upload(f, max_mb=5))

    def test_sheet_validation(self):
        self.assertIsNone(validate_sheet_upload(_FakeFile('a.xlsx', b'PK\x03\x04data')))
        self.assertIsNotNone(validate_sheet_upload(_FakeFile('a.exe', b'MZ')))
        self.assertIsNotNone(validate_sheet_upload(_FakeFile('a.csv', b'')))


class RateLimitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='rl_user', password='test12345', role='student')

    def test_blocks_after_max(self):
        allowed_hits = 0
        for _ in range(5):
            req = self.factory.post('/x/')
            req.user = self.user
            if not rate_limit_hit(req, 'unit_test_rl', 3, 60):
                allowed_hits += 1
        self.assertEqual(allowed_hits, 3)


class SessionTerminationTests(TestCase):
    def test_terminates_other_sessions(self):
        user = User.objects.create_user(username='sess_user', password='test12345', role='student')
        self.assertTrue(self.client.login(username='sess_user', password='test12345'))
        from django.contrib.sessions.models import Session
        self.assertGreaterEqual(Session.objects.count(), 1)
        killed = terminate_user_sessions(user)
        self.assertGreaterEqual(killed, 1)
        self.assertEqual(Session.objects.filter(expire_date__gt=timezone.now()).count(), 0)


class ModelConstraintTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='t_c', password='test12345', role='teacher')
        self.grade, _ = Grade.objects.get_or_create(name='9')

    def _exam(self, **kw):
        params = dict(title='آزمون قیدها', teacher=self.teacher, grade=self.grade,
                      duration_minutes=30,
                      start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1))
        params.update(kw)
        return Exam(**params)

    def test_duration_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._exam(duration_minutes=0).save()

    def test_time_order_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._exam(start_time=timezone.now(), end_time=timezone.now() - timedelta(hours=1)).save()

    def test_valid_exam_ok(self):
        self._exam().save()
        self.assertEqual(Exam.objects.count(), 1)


class AdminValidationViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='adm_v', password='test12345',
                                              role='admin', is_staff=True, is_superuser=True)
        self.client.login(username='adm_v', password='test12345')

    def test_weak_password_rejected(self):
        r = self.client.post('/admin-panel/users/add/',
                             {'username': 'newbie1', 'password': '123', 'role': 'student'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('رمز عبور', r.json()['error'])
        self.assertFalse(User.objects.filter(username='newbie1').exists())

    def test_bad_username_rejected(self):
        r = self.client.post('/admin-panel/users/add/',
                             {'username': 'bad name!', 'password': 'test12345', 'role': 'student'})
        self.assertEqual(r.status_code, 400)

    def test_fake_grade_rejected(self):
        r = self.client.post('/admin-panel/users/add/',
                             {'username': 'okuser1', 'password': 'test12345',
                              'role': 'student', 'grade': '999999'})
        self.assertEqual(r.status_code, 400)

    def test_valid_user_created(self):
        r = self.client.post('/admin-panel/users/add/',
                             {'username': 'okuser2', 'password': 'test12345', 'role': 'student'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(User.objects.filter(username='okuser2').exists())


class TeacherAnnouncementValidationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='t_ann', password='test12345', role='teacher')
        self.client.login(username='t_ann', password='test12345')

    def test_overlong_title_not_saved(self):
        r = self.client.post('/teacher/announce/',
                             {'title': 'ع' * 500, 'body': 'متن'},
                             follow=False)
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(Announcement.objects.count(), 0)

    def test_open_redirect_blocked(self):
        r = self.client.post('/teacher/announce/',
                             {'title': 'سلام', 'body': 'x', 'back': 'https://evil.com'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('evil.com', r['Location'])

    def test_valid_announcement_saved(self):
        r = self.client.post('/teacher/announce/', {'title': 'جلسه فردا', 'body': 'ساعت ۱۰'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Announcement.objects.filter(title='جلسه فردا').count(), 1)
