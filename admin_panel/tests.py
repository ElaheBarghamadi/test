# -*- coding: utf-8 -*-
"""تست‌های پنل مدیر: آمار، مدیریت کاربران و ورود اطلاعات از فایل"""
import io
from datetime import timedelta
from decimal import Decimal

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Grade, User
from admin_panel.views import clean_numeric_text, to_decimal
from exams.models import Exam, Question, StudentAnswer, ExamAttempt


class AdminPanelTestCase(TestCase):
    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.admin = User.objects.create_user(username='admin_t', password='test12345', role='admin',
                                              is_staff=True, is_superuser=True)
        self.teacher = User.objects.create_user(username='teacher_t', password='test12345', role='teacher')
        self.student = User.objects.create_user(username='student_t', password='test12345',
                                                role='student', grade=self.grade,
                                                first_name='زهرا', last_name='محمدی')
        self.client.force_login(self.admin)


class DashboardStatsTests(AdminPanelTestCase):
    """داشبورد و تحلیل دانش‌آموزان قبلاً به‌خاطر ترکیب float و Decimal با خطای 500 باز می‌شدند"""

    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.exam = Exam.objects.create(title='آزمون', teacher=self.teacher, grade=self.grade,
                                        duration_minutes=30, start_time=now - timedelta(days=2),
                                        end_time=now - timedelta(days=1), show_score_to_student=True)
        self.exam.students.set([self.student])
        q1 = Question.objects.create(exam=self.exam, text='q1', question_type='short_answer',
                                     max_score=Decimal('4'), order=1)
        q2 = Question.objects.create(exam=self.exam, text='q2', question_type='short_answer',
                                     max_score=Decimal('2.5'), order=2)
        StudentAnswer.objects.create(student=self.student, question=q1, answer_text='a', score_obtained=3.5)
        StudentAnswer.objects.create(student=self.student, question=q2, answer_text='b', score_obtained=1.25)
        ExamAttempt.objects.create(student=self.student, exam=self.exam, status='submitted',
                                   started_at=now - timedelta(days=2), submitted_at=now - timedelta(days=2))

    def test_admin_dashboard_renders(self):
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_student_analytics_renders(self):
        response = self.client.get(reverse('student_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'زهرا')

    def test_exam_analytics_renders(self):
        self.assertEqual(self.client.get(reverse('exam_analytics')).status_code, 200)

    def test_all_admin_pages_render(self):
        urls = [reverse('admin_dashboard'), reverse('manage_users'), reverse('manage_exams'),
                reverse('exam_detail', kwargs={'exam_id': self.exam.id}),
                reverse('exam_analytics'), reverse('student_analytics'),
                reverse('system_settings'), reverse('system_logs')]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_non_admin_is_redirected(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('admin_dashboard')).status_code, 302)


class HelperTests(TestCase):
    def test_to_decimal(self):
        self.assertEqual(to_decimal(1.5), Decimal('1.5'))
        self.assertEqual(to_decimal('2.25'), Decimal('2.25'))
        self.assertEqual(to_decimal(None), Decimal('0'))
        self.assertEqual(to_decimal('junk'), Decimal('0'))

    def test_clean_numeric_text_strips_excel_float_suffix(self):
        """pandas عدد را float می‌خواند: 140312001 → «140312001.0»"""
        self.assertEqual(clean_numeric_text(140312001.0), '140312001')
        self.assertEqual(clean_numeric_text('140312001.0'), '140312001')
        self.assertEqual(clean_numeric_text(140312001), '140312001')
        self.assertEqual(clean_numeric_text(' ali '), 'ali')
        self.assertEqual(clean_numeric_text(float('nan')), '')
        self.assertEqual(clean_numeric_text(None), '')


class UserManagementTests(AdminPanelTestCase):
    def add_user(self, **over):
        payload = {'username': 'new_u', 'password': 'pass1234', 'first_name': 'تازه',
                   'last_name': 'کاربر', 'role': 'student', 'grade': str(self.grade.id),
                   'student_code': '999001'}
        payload.update(over)
        return self.client.post(reverse('add_user'), payload)

    def test_add_user(self):
        response = self.add_user()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        user = User.objects.get(username='new_u')
        self.assertEqual(user.student_code, '999001')
        self.assertTrue(user.check_password('pass1234'))

    def test_duplicate_username_rejected(self):
        self.add_user()
        response = self.add_user()
        self.assertEqual(response.status_code, 400)

    def test_short_password_rejected(self):
        self.assertEqual(self.add_user(username='shortpw', password='123').status_code, 400)

    def test_missing_username_rejected(self):
        self.assertEqual(self.add_user(username='').status_code, 400)

    def test_edit_user(self):
        self.add_user()
        user = User.objects.get(username='new_u')
        response = self.client.post(reverse('edit_user', kwargs={'user_id': user.id}),
                                    {'username': 'edited_u', 'role': 'student',
                                     'grade': str(self.grade.id), 'student_code': '999002',
                                     'first_name': 'و', 'last_name': 'یرایش'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='edited_u', student_code='999002').exists())

    def test_delete_user_and_self_protection(self):
        self.add_user()
        user = User.objects.get(username='new_u')
        self.assertEqual(self.client.get(reverse('delete_user', kwargs={'user_id': user.id})).status_code, 200)
        self.assertFalse(User.objects.filter(id=user.id).exists())

        response = self.client.get(reverse('delete_user', kwargs={'user_id': self.admin.id}))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(User.objects.filter(id=self.admin.id).exists())

    def test_endpoints_are_post_only(self):
        self.assertEqual(self.client.get(reverse('add_user')).status_code, 405)
        self.assertEqual(self.client.get(reverse('edit_user', kwargs={'user_id': self.student.id})).status_code, 405)

    def test_non_admin_blocked(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse('add_user'), {'username': 'x', 'password': 'pass1234',
                                                                'role': 'student'}).status_code, 403)


class ImportUsersTests(AdminPanelTestCase):
    def upload(self, content: bytes, name):
        return self.client.post(reverse('import_users_from_file'),
                                {'file': SimpleUploadedFile(name, content)})

    def excel(self, rows):
        buf = io.BytesIO()
        pd.DataFrame(rows).to_excel(buf, index=False)
        return buf.getvalue()

    def test_excel_import_with_numeric_student_code(self):
        content = self.excel([
            {'first_name': 'اکسل', 'last_name': 'یک', 'username': 'xl_1', 'password': 12345678,
             'role': 'student', 'student_code': 140312999, 'grade_id': self.grade.id},
            {'first_name': 'اکسل', 'last_name': 'دو', 'username': 'xl_2', 'password': 'pw123456',
             'role': 'student', 'student_code': '140312998', 'grade_id': self.grade.id},
        ])
        response = self.upload(content, 'users.xlsx')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['success_count'], 2, data)

        user = User.objects.get(username='xl_1')
        self.assertEqual(user.student_code, '140312999', 'کد دانش‌آموزی با «.0» ذخیره شده است')
        self.assertTrue(user.check_password('12345678'), 'رمز عبور عددی درست وارد نشده')
        self.assertEqual(user.grade_id, self.grade.id)

    def test_duplicate_rows_are_reported(self):
        content = self.excel([
            {'username': 'dup_1', 'password': 'pw123456', 'role': 'student'},
            {'username': 'dup_1', 'password': 'pw123456', 'role': 'student'},
        ])
        data = self.upload(content, 'users.xlsx').json()
        self.assertEqual(data['success_count'], 1)
        self.assertEqual(data['failed_count'], 1)
        self.assertTrue(data['errors'])

    def test_invalid_role_is_reported(self):
        content = self.excel([{'username': 'bad_role', 'password': 'pw123456', 'role': 'manager'}])
        data = self.upload(content, 'users.xlsx').json()
        self.assertEqual(data['success_count'], 0)
        self.assertEqual(data['failed_count'], 1)

    def test_csv_import_utf8(self):
        content = 'username,password,role,first_name,last_name\ncsv_1,pw123456,student,پارسا,راد\n'
        response = self.upload(content.encode('utf-8'), 'users.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success_count'], 1)
        self.assertTrue(User.objects.filter(username='csv_1', first_name='پارسا').exists())

    def test_csv_import_cp1256(self):
        """فایل CSV خروجی اکسل فارسی معمولاً cp1256 است"""
        content = 'username,password,role,first_name,last_name\ncp_1,pw123456,student,پارسا,راد\n'
        response = self.upload(content.encode('cp1256'), 'users.csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success_count'], 1)
        self.assertEqual(User.objects.get(username='cp_1').first_name, 'پارسا')

    def test_malformed_csv_does_not_crash(self):
        """تعداد ستون داده بیشتر از سرستون → قبلاً خطای 500 می‌داد"""
        content = 'username,password,role,first_name,last_name\nbrk_1,pw123456,student,الف,ب,پ\n'
        response = self.upload(content.encode('utf-8'), 'broken.csv')
        self.assertIn(response.status_code, (200, 400))

    def test_unsupported_extension_rejected(self):
        self.assertEqual(self.upload(b'junk', 'users.txt').status_code, 400)

    def test_missing_file_rejected(self):
        self.assertEqual(self.client.post(reverse('import_users_from_file'), {}).status_code, 400)

    def test_missing_required_column(self):
        content = self.excel([{'first_name': 'بی', 'last_name': 'نام'}])
        self.assertEqual(self.upload(content, 'users.xlsx').status_code, 400)

    def test_non_admin_blocked(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.upload(b'x', 'users.xlsx').status_code, 403)


class SettingsTests(AdminPanelTestCase):
    def test_save_report_card_settings(self):
        response = self.client.post(reverse('system_settings'),
                                    {'action': 'save_report_card', 'show_report_card': 'on',
                                     'min_pass_score': '12', 'current_semester': 'first'})
        self.assertEqual(response.status_code, 200)

    def test_save_security_settings(self):
        response = self.client.post(reverse('system_settings'),
                                    {'action': 'save_security', 'enable_anti_cheat': 'on',
                                     'max_tab_switches': '5'})
        self.assertEqual(response.status_code, 200)

    def test_report_card_setting_reaches_student_dashboard(self):
        from admin_panel.models import SystemSetting
        SystemSetting.set_setting('show_report_card_to_students', 'true', setting_type='report_card')
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_templates_are_downloadable(self):
        response = self.client.get(reverse('download_users_template'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:2], b'PK')
