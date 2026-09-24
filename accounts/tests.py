# -*- coding: utf-8 -*-
"""تست‌های صفحه ورود و جریان احراز هویت"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Grade, User


def make_user(username, role='student', password='test12345', grade=None, **kw):
    user = User.objects.create_user(username=username, password=password, role=role, grade=grade, **kw)
    if role == 'admin':
        user.is_staff = True
        user.is_superuser = True
        user.save()
    return user


class LoginPageStyleTests(TestCase):
    """صفحه ورود باید هم‌شکل بقیه بخش‌های سامانه باشد"""

    OFF_PALETTE = ['#2a5298', '#1e3c72', '#eef2f8', '#1e293b']   # تم آبی/طوسی قدیمی
    SITE_PALETTE = ['#0f7078', '#2ec4b6', '#0a3440']  # تم فیروزه‌ای/نفتی سامانه

    def setUp(self):
        self.response = self.client.get(reverse('login'))
        self.html = self.response.content.decode()

    def test_login_page_renders(self):
        self.assertEqual(self.response.status_code, 200)

    def test_uses_site_palette(self):
        for color in self.SITE_PALETTE:
            self.assertIn(color, self.html, f'رنگ {color} از تم سامانه در صفحه ورود نیست')

    def test_old_blue_palette_removed(self):
        for color in self.OFF_PALETTE:
            self.assertNotIn(color, self.html, f'رنگ {color} مربوط به تم قدیمی هنوز در صفحه ورود است')

    def test_standalone_without_header_footer(self):
        # صفحه ورود به درخواست کاربر بدون هدر و فوتر است
        self.assertNotIn('site-footer', self.html)
        self.assertNotIn('site-header', self.html)
        self.assertIn('سامانه آزمون', self.html)

    def test_form_fields_and_csrf(self):
        self.assertIn('name="username"', self.html)
        self.assertIn('name="password"', self.html)
        self.assertIn('csrfmiddlewaretoken', self.html)


class BrandingTests(TestCase):
    """هیچ اثری از نام مدرسه نباید در صفحات باشد"""

    FORBIDDEN = ['فرزانگان', 'سبزوار', 'farzangan', 'farzanegan', 'sabzevar']

    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.admin = make_user('admin_b', 'admin')
        self.teacher = make_user('teacher_b', 'teacher')
        self.student = make_user('student_b', 'student', grade=self.grade)

    def assert_clean(self, html, url):
        for word in self.FORBIDDEN:
            self.assertNotIn(word.lower(), html.lower(), f'«{word}» هنوز در {url} دیده می‌شود')

    def test_login_page_has_no_school_name(self):
        response = self.client.get(reverse('login'))
        self.assert_clean(response.content.decode(), reverse('login'))

    def test_error_pages_have_no_school_name(self):
        for url in ['/no-such-page/', '/login/']:
            with self.subTest(url=url):
                self.assert_clean(self.client.get(url).content.decode(), url)

    def test_panels_have_no_school_name(self):
        cases = [
            (self.admin, [reverse('admin_dashboard'), reverse('manage_users'), reverse('manage_exams'),
                          reverse('system_logs'), reverse('system_settings')]),
            (self.teacher, [reverse('teacher_dashboard'), reverse('create_exam')]),
            (self.student, [reverse('student_dashboard')]),
        ]
        for user, urls in cases:
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assert_clean(response.content.decode(), url)


class LoginFlowTests(TestCase):
    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.admin = make_user('admin_u', 'admin')
        self.teacher = make_user('teacher_u', 'teacher')
        self.student = make_user('student_u', 'student', grade=self.grade)

    def test_login_redirects_by_role(self):
        cases = [
            ('admin_u', reverse('admin_dashboard')),
            ('teacher_u', reverse('teacher_dashboard')),
            ('student_u', reverse('student_dashboard')),
        ]
        for username, expected_url in cases:
            with self.subTest(username=username):
                self.client.logout()   # هر نقش با سشن تازه وارد شود
                response = self.client.post(reverse('login'),
                                            {'username': username, 'password': 'test12345'})
                self.assertRedirects(response, expected_url, fetch_redirect_response=False)

    def test_wrong_password_shows_error(self):
        response = self.client.post(reverse('login'),
                                    {'username': 'student_u', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'نام کاربری یا رمز عبور اشتباه است')

    def test_unknown_user_shows_error(self):
        response = self.client.post(reverse('login'),
                                    {'username': 'ghost', 'password': 'whatever'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اشتباه')

    def test_authenticated_user_is_redirected_from_login(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('teacher_dashboard'), fetch_redirect_response=False)

    def test_logout_requires_post(self):
        """خروج با GET ممنوع است (جلوگیری از خروج اجباری کاربر با لینک مخرب)"""
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('logout_view')).status_code, 405)
        self.assertTrue(self.client.session.items())

    def test_logout_with_post(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('logout_view'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_protected_panels_redirect_anonymous_users(self):
        for url in [reverse('teacher_dashboard'), reverse('student_dashboard'), reverse('admin_dashboard')]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)

    def test_role_isolation(self):
        # دانش‌آموز نباید بتواند وارد پنل معلم یا ادمین شود (۳۰۲ ریدایرکت یا ۴۰۳ ممنوع)
        self.client.force_login(self.student)
        for url in [reverse('teacher_dashboard'), reverse('admin_dashboard')]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(response.status_code, (302, 403))

        self.client.force_login(self.teacher)
        self.assertIn(self.client.get(reverse('admin_dashboard')).status_code, (302, 403))


# =====================================================================
#  تست‌های امنیت و کنترل دسترسی
# =====================================================================
import json as _json
import os as _os
import shutil as _shutil
import tempfile as _tempfile
from datetime import timedelta as _timedelta
from decimal import Decimal as _Decimal

from django.test import override_settings as _override_settings
from django.utils import timezone as _tz

from exams.models import Exam as _Exam, Question as _Question, \
    StudentAnswer as _StudentAnswer, ExamAttempt as _ExamAttempt
from student_panel.views import hash_exam_id as _hash_exam_id

_TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02'
    b'\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x03'
    b'\x01\xa5\xac\x8f\xa6\xbb\x00\x00\x00\x00IEND\xaeB`\x82'
)


class SecurityFixtureMixin:
    """ساخت سناریوی کامل: دو معلم، سه دانش‌آموز، مدیر، آزمون با تصویر"""

    def setUp(self):
        self.media_root = _tempfile.mkdtemp(prefix='media-test-')
        for sub in ('question_images', 'student_answers', 'teacher_answers'):
            _os.makedirs(_os.path.join(self.media_root, sub), exist_ok=True)

        self.grade9 = Grade.objects.create(name='9')
        self.grade8 = Grade.objects.create(name='8')
        self.teacher_a = make_user('teacher_a', role='teacher')
        self.teacher_b = make_user('teacher_b', role='teacher')
        self.student1 = make_user('student1', grade=self.grade9)
        self.student2 = make_user('student2', grade=self.grade9)
        self.student8 = make_user('student8', grade=self.grade8)
        self.admin = make_user('admin_u', role='admin')

        now = _tz.now()
        self.exam = _Exam.objects.create(
            title='security exam', teacher=self.teacher_a, grade=self.grade9,
            duration_minutes=30, start_time=now - _timedelta(hours=1),
            end_time=now + _timedelta(hours=2),
        )
        self.exam.students.set([self.student1])

        self.q = _Question.objects.create(exam=self.exam, text='q', question_type='short_answer',
                                          max_score=_Decimal('2'), order=1)
        self.q_img = _Question.objects.create(exam=self.exam, text='qi', question_type='short_answer',
                                              max_score=_Decimal('2'), order=2)
        self.q_img.image.name = 'question_images/sec_q.png'
        self.q_img.save()
        self._write_media('question_images/sec_q.png')

        self.answer = _StudentAnswer.objects.create(student=self.student1, question=self.q,
                                                    answer_text='my answer')
        self.answer.answer_image.name = 'student_answers/sec_a.png'
        self.answer.save()
        self._write_media('student_answers/sec_a.png')

        self.hash = _hash_exam_id(self.exam.id)

    def tearDown(self):
        _shutil.rmtree(self.media_root, ignore_errors=True)

    def _write_media(self, rel):
        with open(_os.path.join(self.media_root, rel), 'wb') as f:
            f.write(_TINY_PNG)


class AccessControlMatrixTests(SecurityFixtureMixin, TestCase):
    """ماتریس دسترسی: هر نقش فقط باید صفحه‌های خودش را ببیند"""

    def setUp(self):
        super().setUp()
        # override_settings decorator cannot use instance tempdir; patch directly
        from django.conf import settings as dj_settings
        self._old_media = dj_settings.MEDIA_ROOT
        dj_settings.MEDIA_ROOT = self.media_root

    def tearDown(self):
        from django.conf import settings as dj_settings
        dj_settings.MEDIA_ROOT = self._old_media
        super().tearDown()

    # ---------- ناشناس ----------
    def test_anonymous_redirected_everywhere(self):
        urls = [
            reverse('student_dashboard'), reverse('teacher_dashboard'), reverse('admin_dashboard'),
            f'/student/exam/{self.hash}/', reverse('create_exam'), reverse('manage_users'),
            reverse('manage_exams'),
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 302)
                self.assertIn('/login', res['Location'])
        # اندپوینت فقط-POST هم برای ناشناس قابل دسترسی نیست
        self.assertIn(self.client.get(reverse('save_answer')).status_code, (302, 405))

    # ---------- دانش‌آموز ↔ معلم ↔ مدیر ----------
    def test_student_cannot_open_teacher_pages(self):
        self.client.force_login(self.student1)
        urls = [
            reverse('teacher_dashboard'), reverse('create_exam'),
            reverse('edit_exam_info', kwargs={'exam_id': self.exam.id}),
            reverse('grade_exam', kwargs={'exam_id': self.exam.id}),
            reverse('exam_results', kwargs={'exam_id': self.exam.id}),
            reverse('view_student_answers', kwargs={'exam_id': self.exam.id}),
            reverse('exam_cheats_report', kwargs={'exam_id': self.exam.id}),
            reverse('print_exam_paper', kwargs={'exam_id': self.exam.id}),
            reverse('print_answer_sheet', kwargs={'exam_id': self.exam.id}),
            reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}),
            reverse('exam_settings', kwargs={'exam_id': self.exam.id}),
            reverse('delete_exam', kwargs={'exam_id': self.exam.id}),
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertIn(res.status_code, (302, 403, 404))
                if res.status_code == 302:
                    self.assertEqual(res['Location'], '/')

    def test_student_cannot_open_admin_pages(self):
        self.client.force_login(self.student1)
        for url in [reverse('admin_dashboard'), reverse('manage_users'), reverse('manage_exams'),
                    reverse('system_settings'), reverse('system_logs'), reverse('backup_data')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_teacher_cannot_open_admin_or_student_pages(self):
        self.client.force_login(self.teacher_a)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 302)
        self.assertEqual(self.client.get(f'/student/exam/{self.hash}/').status_code, 403)

    def test_admin_cannot_open_teacher_pages(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse('teacher_dashboard'))
        self.assertIn(res.status_code, (302, 403))

    # ---------- معلم دیگر (IDOR) ----------
    def test_other_teacher_blocked_from_exam_pages(self):
        self.client.force_login(self.teacher_b)
        urls = [
            reverse('edit_exam_info', kwargs={'exam_id': self.exam.id}),
            reverse('edit_exam', kwargs={'exam_id': self.exam.id}),
            reverse('exam_settings', kwargs={'exam_id': self.exam.id}),
            reverse('delete_exam', kwargs={'exam_id': self.exam.id}),
            reverse('toggle_exam_status', kwargs={'exam_id': self.exam.id}),
            reverse('add_question', kwargs={'exam_id': self.exam.id}),
            reverse('grade_exam', kwargs={'exam_id': self.exam.id}),
            reverse('exam_results', kwargs={'exam_id': self.exam.id}),
            reverse('view_student_answers', kwargs={'exam_id': self.exam.id}),
            reverse('exam_cheats_report', kwargs={'exam_id': self.exam.id}),
            reverse('print_exam_paper', kwargs={'exam_id': self.exam.id}),
            reverse('print_answer_sheet', kwargs={'exam_id': self.exam.id}),
            reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (403, 404))

    def test_other_teacher_cannot_delete_question_or_save_score(self):
        self.client.force_login(self.teacher_b)
        res = self.client.get(reverse('delete_question',
                                      kwargs={'exam_id': self.exam.id, 'question_id': self.q.id}))
        self.assertIn(res.status_code, (403, 404))
        self.assertTrue(_Question.objects.filter(id=self.q.id).exists())

        res = self.client.post(reverse('save_score'),
                               {'answer_id': self.answer.id, 'score': '2'})
        self.assertEqual(res.status_code, 403)


    # ---------- دانش‌آموز غیرعضو / پایه دیگر ----------
    def test_non_enrolled_student_blocked(self):
        self.client.force_login(self.student2)
        self.assertEqual(self.client.get(f'/student/exam/{self.hash}/').status_code, 403)
        self.assertEqual(self.client.get(reverse('check_exam_time',
                                                 kwargs={'hashed_exam_id': self.hash})).status_code, 403)
        res = self.client.post(reverse('save_answer'),
                               data=_json.dumps({'question_id': self.q.id, 'answer_text': 'x'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 403)
        res = self.client.get(reverse('submit_exam', kwargs={'hashed_exam_id': self.hash}))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.get(reverse('exam_result_detail',
                                                 kwargs={'exam_id': self.exam.id})).status_code, 302)

    def test_other_grade_student_blocked(self):
        self.client.force_login(self.student8)
        self.assertEqual(self.client.get(f'/student/exam/{self.hash}/').status_code, 403)

    # ---------- دانش‌آموز عضو: دسترسی مجاز ----------
    def test_enrolled_student_allowed(self):
        self.client.force_login(self.student1)
        self.assertEqual(self.client.get(f'/student/exam/{self.hash}/').status_code, 200)
        self.assertEqual(self.client.get(reverse('check_exam_time',
                                                 kwargs={'hashed_exam_id': self.hash})).status_code, 200)

    def test_save_answer_before_exam_start_blocked(self):
        now = _tz.now()
        future = _Exam.objects.create(title='future', teacher=self.teacher_a, grade=self.grade9,
                                      duration_minutes=10, start_time=now + _timedelta(hours=1),
                                      end_time=now + _timedelta(hours=2))
        future.students.set([self.student1])
        qf = _Question.objects.create(exam=future, text='q', question_type='short_answer',
                                      max_score=_Decimal('1'), order=1)
        self.client.force_login(self.student1)
        res = self.client.post(reverse('save_answer'),
                               data=_json.dumps({'question_id': qf.id, 'answer_text': 'zood'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 403)


class ProtectedMediaTests(SecurityFixtureMixin, TestCase):
    """فایل‌های آپلودشده باید فقط برای افراد مجاز قابل دیدن باشند"""

    def setUp(self):
        super().setUp()
        from django.conf import settings as dj_settings
        self._old_media = dj_settings.MEDIA_ROOT
        dj_settings.MEDIA_ROOT = self.media_root

    def tearDown(self):
        from django.conf import settings as dj_settings
        dj_settings.MEDIA_ROOT = self._old_media
        super().tearDown()

    def get(self, rel):
        return self.client.get(f'/media/{rel}')

    def test_question_image_access(self):
        cases = [
            (None, 302),            # ناشناس → ورود
            ('student1', 200),      # عضو آزمون
            ('student2', 403),      # هم‌پایه ولی غیرعضو
            ('student8', 403),      # پایه دیگر
            ('teacher_a', 200),     # معلم سازنده
            ('teacher_b', 403),     # معلم دیگر
            ('admin_u', 200),       # مدیر
        ]
        for username, expected in cases:
            with self.subTest(user=username):
                self.client.logout()
                if username:
                    self.client.force_login(User.objects.get(username=username))
                self.assertEqual(self.get('question_images/sec_q.png').status_code, expected)

    def test_student_answer_image_access(self):
        cases = [
            (None, 302),
            ('student1', 200),      # صاحب پاسخ
            ('student2', 403),      # دانش‌آموز دیگر
            ('teacher_a', 200),     # معلم آزمون
            ('teacher_b', 403),
            ('admin_u', 200),
        ]
        for username, expected in cases:
            with self.subTest(user=username):
                self.client.logout()
                if username:
                    self.client.force_login(User.objects.get(username=username))
                self.assertEqual(self.get('student_answers/sec_a.png').status_code, expected)

    def test_unknown_or_traversed_path_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.get('question_images/nope.png').status_code, 404)
        self.assertEqual(self.get('../db.sqlite3').status_code, 404)
        self.assertEqual(self.get('secret.txt').status_code, 404)


class LoginThrottleTests(TestCase):
    """پس از چند بار تلاش ناموفق، ورود موقتاً قفل شود"""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = make_user('throttle_u', role='student')

    def _post(self, password):
        return self.client.post(reverse('login'),
                                {'username': 'throttle_u', 'password': password})

    def test_locks_after_repeated_failures(self):
        for _ in range(7):
            self._post('wrong')
        res = self._post('test12345')   # حتی رمز درست هم در دوران قفل رد می‌شود
        self.assertEqual(res.status_code, 429)
        self.assertIn('چند دقیقه دیگر', res.content.decode())

    def test_normal_login_unaffected(self):
        for _ in range(3):
            self._post('wrong')
        res = self._post('test12345')
        self.assertEqual(res.status_code, 302)


class SecurityHeadersTests(TestCase):
    def test_security_headers_present(self):
        res = self.client.get(reverse('login'))
        self.assertEqual(res.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertIn(res.headers.get('X-Frame-Options'), ('DENY', 'SAMEORIGIN'))
        self.assertIn('strict-origin', res.headers.get('Referrer-Policy', ''))


class BrandedNotFoundTests(TestCase):
    """صفحه ۴۰۴ برندشده حتی وقتی DEBUG روشن است؛ درخواست‌های غیرHTML دست‌نخورده"""

    @_override_settings(DEBUG=True)
    def test_html_404_is_branded_even_in_debug(self):
        r = self.client.get('/no-such-page-xyz/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, '۴۰۴', status_code=404)

    @_override_settings(DEBUG=True)
    def test_non_html_404_not_swallowed_in_debug(self):
        r = self.client.get('/no-such-page-xyz/', HTTP_ACCEPT='application/json')
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('۴۰۴', r.content.decode('utf-8', 'ignore'))

    def test_html_404_branded_in_production_mode(self):
        r = self.client.get('/no-such-page-xyz/', HTTP_ACCEPT='text/html')
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, '۴۰۴', status_code=404)
