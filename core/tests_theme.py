# -*- coding: utf-8 -*-
"""تست‌های یکپارچگی تم و ریسپانسیو

این مجموعه همان چیزهایی را خودکار می‌سنجد که در بازبینی دستی بررسی شد:
  • هر صفحهٔ کامل باید dir="rtl" و lang="fa" داشته باشد
  • هر صفحهٔ کامل باید متاتگ viewport داشته باشد و زوم کاربر را نبندد
  • هیچ صفحه‌ای نباید با ۵۰۰ سقوط کند یا traceback نشت دهد
  • کاربر ناشناس باید به /login/ برود، نه به /accounts/login/ که وجود ندارد
  • دارایی‌های استاتیک ارجاع‌شده باید واقعی باشند
"""
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Grade, User
from exams.models import Exam, ExamAttempt, Question, StudentAnswer
from student_panel.views import hash_exam_id

VIEWPORT_RE = re.compile(r'<meta[^>]+name=["\']viewport["\'][^>]*>', re.I)
RTL_RE = re.compile(r'<html[^>]+dir=["\']rtl["\']', re.I)
LANG_RE = re.compile(r'<html[^>]+lang=["\']fa', re.I)
THEME_COLOR_RE = re.compile(r'<meta[^>]+name=["\']theme-color["\']', re.I)
TRACEBACK_RE = re.compile(r'Traceback \(most recent call last\)|Exception Type|TemplateDoesNotExist|NoReverseMatch')
STATIC_HREF_RE = re.compile(r'(?:href|src)=["\'](/static/[^"\']+)["\']')


class ThemeTestCase(TestCase):
    """پایهٔ مشترک: یک کاربر از هر نقش + یک آزمون کامل با همهٔ انواع سوال"""

    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.admin = User.objects.create_user(username='a_theme', password='test12345',
                                              role='admin', is_staff=True, is_superuser=True)
        self.teacher = User.objects.create_user(username='t_theme', password='test12345', role='teacher')
        self.student = User.objects.create_user(username='s_theme', password='test12345',
                                                role='student', grade=self.grade)
        now = timezone.now()
        self.exam = Exam.objects.create(title='آزمون تم', teacher=self.teacher, grade=self.grade,
                                        duration_minutes=30, start_time=now - timedelta(hours=1),
                                        end_time=now + timedelta(hours=2),
                                        show_score_to_student=True, show_answers_after_exam=True)
        self.exam.students.set([self.student])
        for i, qtype in enumerate(['true_false', 'multiple_choice', 'fill_blank', 'short_answer',
                                   'long_answer', 'matching'], start=1):
            Question.objects.create(exam=self.exam, text=f'سوال {i}', question_type=qtype,
                                    max_score=Decimal('2'), order=i,
                                    options=['الف', 'ب'] if qtype == 'multiple_choice' else [],
                                    correct_answer='1' if qtype == 'true_false' else '')
        self.hashed = hash_exam_id(self.exam.id)

        # تلاش ثبت‌نهایی‌شده + پاسخ‌ها → تا صفحهٔ «جزئیات نتیجه» واقعاً رندر شود
        # (بدون آن، exam_result_detail به داشبورد redirect می‌کند و ۳۰۲ می‌شود)
        self.attempt = ExamAttempt.objects.create(student=self.student, exam=self.exam,
                                                  status='submitted',
                                                  started_at=now - timedelta(minutes=20),
                                                  submitted_at=now - timedelta(minutes=5))
        for q in self.exam.questions.all():
            StudentAnswer.objects.create(student=self.student, question=q,
                                         answer_text='پاسخ نمونه', score_obtained=1.5)

        # آزمون دوم «ثبت‌نشده» برای تست صفحهٔ خودِ آزمون
        # (take_exam به تلاشِ submitted اجازهٔ ورود نمی‌دهد و redirect می‌کند)
        self.open_exam = Exam.objects.create(title='آزمون باز', teacher=self.teacher, grade=self.grade,
                                             duration_minutes=45, start_time=now - timedelta(hours=1),
                                             end_time=now + timedelta(hours=3))
        self.open_exam.students.set([self.student])
        for i, qtype in enumerate(['true_false', 'multiple_choice', 'short_answer'], start=1):
            Question.objects.create(exam=self.open_exam, text=f'سوال {i}', question_type=qtype,
                                    max_score=Decimal('2'), order=i,
                                    options=['الف', 'ب'] if qtype == 'multiple_choice' else [],
                                    correct_answer='1' if qtype == 'true_false' else '')
        self.open_hashed = hash_exam_id(self.open_exam.id)

    def assertHealthyPage(self, res, label=''):
        """هیچ صفحه‌ای نباید ۵۰۰ شود یا خطای قالب نشت دهد"""
        self.assertNotEqual(res.status_code, 500, f'{label}: صفحه با ۵۰۰ سقوط کرد')
        content = res.content.decode('utf-8', 'replace')
        self.assertNotRegex(content, TRACEBACK_RE, f'{label}: خطای پایتون/قالب در صفحه نشت کرده')
        return content

    def assertPageTheme(self, content, label=''):
        """صفحهٔ کامل باید RTL، فارسی و دارای viewport باشد"""
        self.assertRegex(content, RTL_RE, f'{label}: <html dir="rtl"> ندارد')
        self.assertRegex(content, LANG_RE, f'{label}: <html lang="fa"> ندارد')
        self.assertRegex(content, VIEWPORT_RE, f'{label}: متاتگ viewport ندارد (موبایل با عرض دسکتاپ رندر می‌شود)')

    def assertZoomNotBlocked(self, content, label=''):
        """زوم انگشتی نباید بسته شود — برای دسترسی‌پذیری ضروری است"""
        m = VIEWPORT_RE.search(content)
        if not m:
            return
        vp = m.group(0).lower()
        self.assertNotIn('user-scalable=no', vp, f'{label}: زوم کاربر با user-scalable=no بسته شده')
        self.assertNotIn('maximum-scale=1', vp,
                         f'{label}: maximum-scale=1 روی iOS زوم را می‌بندد → {vp}')


class LandingAndAuthThemeTests(ThemeTestCase):
    def test_home_page_theme(self):
        content = self.assertHealthyPage(self.client.get(reverse('home')), 'خانه')
        self.assertPageTheme(content, 'خانه')
        self.assertZoomNotBlocked(content, 'خانه')
        self.assertRegex(content, THEME_COLOR_RE, 'خانه: متاتگ theme-color ندارد')

    def test_home_has_mobile_navigation(self):
        """رگرسیون: منوی ناوبری زیر ۹۰۰px مخفی می‌شد و هیچ جایگزینی نداشت،
        پس در موبایل همهٔ پیوندها ناپدید می‌شدند.

        صفحهٔ فرود حالا از base.html ارث می‌برد، پس همبرگر و کشوی مشترکِ
        بقیهٔ سایت را می‌گیرد. پیوندهای بخش‌ها از templates/_landing_nav.html
        می‌آیند که یک‌بار تعریف و در دو جا (نوار دسکتاپ و کشوی موبایل) include
        می‌شود — این تست همان «دو جا» بودن را قفل می‌کند.
        """
        content = self.client.get(reverse('home')).content.decode()
        self.assertIn('id="hamburger"', content, 'دکمهٔ منوی موبایل در صفحهٔ فرود نیست')
        self.assertIn('id="sidebarMenu"', content, 'کشوی منوی موبایل در صفحهٔ فرود نیست')
        self.assertIn('aria-expanded', content, 'دکمهٔ منو aria-expanded ندارد')
        self.assertIn('aria-controls', content, 'دکمهٔ منو aria-controls ندارد')
        self.assertIn('site-footer', content, 'صفحهٔ فرود باید پانوشت مشترک base.html را داشته باشد')
        for anchor in ('#features', '#question-types', '#how', '#roles', '#security'):
            self.assertGreaterEqual(content.count(anchor), 2,
                                    f'{anchor} باید هم در منوی دسکتاپ و هم در کشوی موبایل باشد')

    def test_login_page_theme(self):
        content = self.assertHealthyPage(self.client.get(reverse('login')), 'ورود')
        self.assertPageTheme(content, 'ورود')
        self.assertZoomNotBlocked(content, 'ورود')

    def test_login_url_setting_points_to_real_page(self):
        """رگرسیون: LOGIN_URL تنظیم نشده بود و جنگو به پیش‌فرض /accounts/login/
        می‌فرستاد که در این پروژه وجود ندارد → صفحهٔ ۴۰۴."""
        self.assertEqual(settings.LOGIN_URL, 'login')
        self.assertEqual(reverse(settings.LOGIN_URL), '/login/')
        res = self.client.get('/accounts/login/')
        self.assertEqual(res.status_code, 404, '/accounts/login/ نباید وجود داشته باشد')

    def test_anonymous_is_redirected_to_working_login_page(self):
        protected = ['/teacher/dashboard/', '/student/dashboard/', '/admin-panel/',
                     '/teacher/bank/', '/student/results/', '/control-center/']
        for path in protected:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, f'{path}: باید کاربر ناشناس را هدایت کند')
            self.assertIn('/login/', res['Location'], f'{path}: به صفحهٔ ورود واقعی هدایت نمی‌شود')
            self.assertNotIn('/accounts/login/', res['Location'], f'{path}: به مسیر ۴۰۴ هدایت می‌شود')
            followed = self.client.get(res['Location'])
            self.assertEqual(followed.status_code, 200, f'{path}: صفحهٔ ورود مقصد ۲۰۰ نیست')

    def test_error_page_theme(self):
        res = self.client.get('/این-صفحه-وجود-ندارد/')
        self.assertEqual(res.status_code, 404)
        content = self.assertHealthyPage(res, '۴۰۴')
        self.assertPageTheme(content, '۴۰۴')
        self.assertZoomNotBlocked(content, '۴۰۴')


class AdminPanelThemeTests(ThemeTestCase):
    PAGES = [
        'admin_dashboard', 'manage_users', 'manage_exams', 'exam_analytics',
        'student_analytics', 'system_logs', 'system_settings',
    ]

    def test_all_admin_pages_are_healthy_and_themed(self):
        self.client.force_login(self.admin)
        for name in self.PAGES:
            res = self.client.get(reverse(name))
            content = self.assertHealthyPage(res, name)
            self.assertEqual(res.status_code, 200, f'{name}: انتظار ۲۰۰ بود')
            self.assertPageTheme(content, name)
            self.assertZoomNotBlocked(content, name)

    def test_admin_detail_pages_are_healthy(self):
        self.client.force_login(self.admin)
        for name, kwargs in [('user_detail', {'user_id': self.student.id}),
                             ('exam_detail', {'exam_id': self.exam.id})]:
            res = self.client.get(reverse(name, kwargs=kwargs))
            content = self.assertHealthyPage(res, name)
            self.assertEqual(res.status_code, 200, f'{name}: انتظار ۲۰۰ بود')
            self.assertPageTheme(content, name)

    def test_control_center_pages_are_healthy(self):
        self.client.force_login(self.admin)
        for name in ['control_dashboard', 'control_users', 'control_staff']:
            res = self.client.get(reverse(name))
            content = self.assertHealthyPage(res, name)
            self.assertEqual(res.status_code, 200, f'{name}: انتظار ۲۰۰ بود')
            self.assertPageTheme(content, name)


class TeacherPanelThemeTests(ThemeTestCase):
    def test_all_teacher_pages_are_healthy_and_themed(self):
        self.client.force_login(self.teacher)
        q = self.exam.questions.first()
        targets = [
            ('teacher_dashboard', {}), ('create_exam', {}), ('question_bank', {}),
            ('bank_question_new', {}), ('groups', {}),
            ('edit_exam', {'exam_id': self.exam.id}),
            ('edit_exam_info', {'exam_id': self.exam.id}),
            ('exam_settings', {'exam_id': self.exam.id}),
            ('exam_results', {'exam_id': self.exam.id}),
            ('grade_exam', {'exam_id': self.exam.id}),
            ('view_student_answers', {'exam_id': self.exam.id}),
            ('exam_cheats_report', {'exam_id': self.exam.id}),
            ('print_exam_paper', {'exam_id': self.exam.id}),
            ('print_answer_sheet', {'exam_id': self.exam.id}),
            ('bulk_upload_questions', {'exam_id': self.exam.id}),
            ('add_question', {'exam_id': self.exam.id}),
            ('edit_question', {'exam_id': self.exam.id, 'question_id': q.id}),
            ('add_teacher_answer', {'exam_id': self.exam.id, 'question_id': q.id}),
        ]
        for name, kwargs in targets:
            res = self.client.get(reverse(name, kwargs=kwargs))
            content = self.assertHealthyPage(res, name)
            self.assertEqual(res.status_code, 200, f'{name}: انتظار ۲۰۰ بود')
            self.assertPageTheme(content, name)
            self.assertZoomNotBlocked(content, name)

    def test_dashboard_uses_the_unified_design_system(self):
        """داشبوردها باید از همان سیستم طراحیِ بقیهٔ سایت استفاده کنند.

        رگرسیون: قبلاً داشبوردها modern.css را جداگانه بارگذاری می‌کردند و
        پوستهٔ کلاسیک base.html با کلاس‌های nx درونش ترکیب می‌شد؛ یعنی دو
        سیستم طراحی موازی در یک صفحه. modern.css حذف شده است.
        """
        for user, name in [(self.teacher, 'teacher_dashboard'), (self.student, 'student_dashboard')]:
            self.client.force_login(user)
            content = self.client.get(reverse(name)).content.decode()
            self.assertIn('css/site.css', content, f'{name}: site.css بارگذاری نمی‌شود')
            self.assertNotIn('modern.css', content,
                             f'{name}: modern.css حذف شده و نباید ارجاع شود')
            self.assertNotRegex(content, r'\bnx-[a-z]',
                                f'{name}: هنوز کلاس nx- دارد و با بقیهٔ سایت یکدست نیست')
            # کامپوننت‌های کلاسیک مشترک باید واقعاً استفاده شوند
            for cls in ('welcome-card', 'stat-card'):
                self.assertIn(cls, content, f'{name}: کامپوننت مشترک {cls} استفاده نشده')

    def test_teacher_and_student_dashboards_agree_on_asset_versions(self):
        """نسخهٔ دارایی‌های مشترک باید در همهٔ قالب‌ها یکسان باشد تا کش مرورگر
        یک نسخهٔ کهنهٔ CSS را با یک نسخهٔ تازهٔ HTML جفت نکند."""
        versions = {}
        for user, name in [(self.teacher, 'teacher_dashboard'), (self.student, 'student_dashboard')]:
            self.client.force_login(user)
            content = self.client.get(reverse(name)).content.decode()
            for asset, ver in re.findall(r"(?:css|js)/(modern\.(?:css|js))'?\s*%?\}?\"?\?v=(\d+)", content):
                versions.setdefault(asset, set()).add(ver)
            for asset, ver in re.findall(r'(modern\.(?:css|js))\?v=(\d+)', content):
                versions.setdefault(asset, set()).add(ver)
        for asset, vers in versions.items():
            self.assertEqual(len(vers), 1, f'{asset} با نسخه‌های ناهمسان بارگذاری می‌شود: {vers}')


class StudentPanelThemeTests(ThemeTestCase):
    def test_all_student_pages_are_healthy_and_themed(self):
        self.client.force_login(self.student)
        targets = [
            ('student_dashboard', {}),
            ('student_results', {}),
            ('exam_result_detail', {'exam_id': self.exam.id}),
            ('take_exam', {'hashed_exam_id': self.open_hashed}),
            ('exam_thanks', {'hashed_exam_id': self.hashed}),
        ]
        for name, kwargs in targets:
            res = self.client.get(reverse(name, kwargs=kwargs))
            content = self.assertHealthyPage(res, name)
            self.assertEqual(res.status_code, 200, f'{name}: انتظار ۲۰۰ بود')
            self.assertPageTheme(content, name)
            self.assertZoomNotBlocked(content, name)

    def test_exam_page_is_mobile_ready(self):
        """صفحهٔ آزمون مهم‌ترین صفحهٔ موبایل است"""
        self.client.force_login(self.student)
        content = self.client.get(reverse('take_exam', kwargs={'hashed_exam_id': self.open_hashed})).content.decode()
        self.assertIn('viewport-fit=cover', content, 'صفحهٔ آزمون safe-area موبایل را در نظر نگرفته')
        self.assertRegex(content, r'@media', 'صفحهٔ آزمون هیچ قانون ریسپانسیوی ندارد')


class StaticAssetTests(ThemeTestCase):
    def test_base_template_has_theme_color(self):
        """رگرسیون: base.html متاتگ theme-color نداشت و نوار مرورگر گوشی
        روی همهٔ صفحات پنل همرنگ پیش‌فرض خاکستری بود."""
        self.client.force_login(self.student)
        content = self.client.get(reverse('student_dashboard')).content.decode()
        self.assertRegex(content, THEME_COLOR_RE, 'base.html متاتگ theme-color ندارد')

    def test_all_referenced_static_assets_exist(self):
        """هر دارایی استاتیکی که در قالب‌ها ارجاع شده باید روی دیسک وجود داشته باشد.

        قالب‌ها از `{% static 'css/site.css' %}` استفاده می‌کنند، پس الگو باید
        هم آن شکل و هم مسیرهای لغوی `/static/...` را بگیرد.
        """
        static_root = settings.BASE_DIR / 'static'
        # {% static 'path' %}  یا  {% static "path" %}
        static_tag_re = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]\s*%\}""")
        checked = 0
        for tpl_name in ['base.html', 'home.html', 'login.html', '_footer.html',
                         'student_panel/take_exam.html', 'student_panel/dashboard.html',
                         'teacher_panel/dashboard.html', 'errors/error.html']:
            path = settings.BASE_DIR / 'templates' / tpl_name
            if not path.exists():
                continue
            src = path.read_text(encoding='utf-8')
            refs = static_tag_re.findall(src)
            refs += [u.split('/static/', 1)[1] for u in STATIC_HREF_RE.findall(src)]
            for rel in refs:
                rel = rel.split('?')[0]
                self.assertTrue((static_root / rel).exists(),
                                f'{tpl_name} به دارایی ناموجود static/{rel} ارجاع می‌دهد')
                checked += 1
        self.assertGreater(checked, 0, 'هیچ ارجاع استاتیکی پیدا نشد — الگوی تست اشتباه است')

    def test_font_files_exist(self):
        static_root = settings.BASE_DIR / 'static' / 'fonts'
        for weight in ['Regular', 'Medium', 'Bold', 'ExtraBold']:
            self.assertTrue((static_root / f'Vazirmatn-{weight}.woff2').exists(),
                            f'فونت Vazirmatn-{weight}.woff2 موجود نیست')
