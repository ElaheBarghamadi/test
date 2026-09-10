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
    SITE_PALETTE = ['#a07830', '#8b6914', '#c49a2b', '#5a3e2b']  # تم طلایی/قهوه‌ای سامانه

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

    def test_extends_base_layout(self):
        # نوار بالا و فوتر مثل بقیه صفحات نمایش داده می‌شوند
        self.assertIn('navbar', self.html)
        self.assertIn('footer', self.html)
        self.assertIn('سامانه آزمون', self.html)

    def test_form_fields_and_csrf(self):
        self.assertIn('name="username"', self.html)
        self.assertIn('name="password"', self.html)
        self.assertIn('csrfmiddlewaretoken', self.html)


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

    def test_logout(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('logout_view'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_protected_panels_redirect_anonymous_users(self):
        for url in [reverse('teacher_dashboard'), reverse('student_dashboard'), reverse('admin_dashboard')]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)

    def test_role_isolation(self):
        # دانش‌آموز نباید بتواند وارد پنل معلم یا ادمین شود
        self.client.force_login(self.student)
        for url in [reverse('teacher_dashboard'), reverse('admin_dashboard')]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)

        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 302)
