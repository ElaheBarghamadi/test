# -*- coding: utf-8 -*-
"""تست‌های پنل دانش‌آموز: داشبورد، ورود به آزمون، ذخیره پاسخ و ثبت تخلف"""
import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Grade, User
from exams.models import Exam, Question, StudentAnswer, ExamAttempt, CheatAttempt
from student_panel.views import hash_exam_id, get_exam_semester, get_current_semester


def make_student(username='student_p', grade=None, password='test12345'):
    return User.objects.create_user(username=username, password=password, role='student', grade=grade)


class StudentPanelTestCase(TestCase):
    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.other_grade = Grade.objects.create(name='8')
        self.teacher = User.objects.create_user(username='teacher_p', password='test12345', role='teacher')
        self.student = make_student(grade=self.grade)
        self.now = timezone.now()

    def make_exam(self, title='exam', start=None, end=None, students=None, **kw):
        exam = Exam.objects.create(
            title=title, teacher=self.teacher, grade=self.grade,
            duration_minutes=kw.pop('duration_minutes', 30),
            start_time=start if start is not None else self.now - timedelta(hours=1),
            end_time=end if end is not None else self.now + timedelta(hours=2),
            **kw
        )
        exam.students.set(students if students is not None else [self.student])
        return exam

    def exam_url(self, exam, view='take_exam'):
        return reverse(view, kwargs={'hashed_exam_id': hash_exam_id(exam.id)})


class DashboardTests(StudentPanelTestCase):
    def test_dashboard_renders(self):
        self.client.force_login(self.student)
        self.make_exam()
        self.assertEqual(self.client.get(reverse('student_dashboard')).status_code, 200)

    def test_dashboard_with_null_submitted_at(self):
        """قبلاً attempt.updated_at وجود نداشت و داشبورد با خطای 500 باز می‌شد"""
        exam = self.make_exam(show_score_to_student=True)
        question = Question.objects.create(exam=exam, text='q', question_type='short_answer',
                                           max_score=Decimal('2'), order=1)
        StudentAnswer.objects.create(student=self.student, question=question, answer_text='a',
                                     score_obtained=1.5)
        ExamAttempt.objects.create(student=self.student, exam=exam, status='submitted',
                                   started_at=self.now, submitted_at=None)

        self.client.force_login(self.student)
        response = self.client.get(reverse('student_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_report_card_and_average_render(self):
        exam = self.make_exam(show_score_to_student=True)
        q = Question.objects.create(exam=exam, text='q', question_type='short_answer',
                                    max_score=Decimal('4'), order=1)
        StudentAnswer.objects.create(student=self.student, question=q, answer_text='a', score_obtained=3.0)
        ExamAttempt.objects.create(student=self.student, exam=exam, status='submitted',
                                   started_at=self.now, submitted_at=self.now)
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'کارنامه')


class TakeExamAccessTests(StudentPanelTestCase):
    def test_inactive_exam_page_exists(self):
        """قبلاً قالب student_panel/exam_inactive.html وجود نداشت → خطای 500"""
        exam = self.make_exam(is_active=False)
        self.client.force_login(self.student)
        response = self.client.get(self.exam_url(exam))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'غیرفعال')

    def test_future_exam_is_not_enterable(self):
        exam = self.make_exam(start=self.now + timedelta(days=1), end=self.now + timedelta(days=1, hours=2))
        self.client.force_login(self.student)
        response = self.client.get(self.exam_url(exam))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'شروع نشده')
        self.assertFalse(ExamAttempt.objects.filter(student=self.student, exam=exam).exists(),
                         'برای آزمون شروع‌نشده نباید تلاش ثبت شود')

    def test_ended_exam_is_not_enterable_for_new_attempt(self):
        exam = self.make_exam(start=self.now - timedelta(days=2), end=self.now - timedelta(days=1))
        self.client.force_login(self.student)
        response = self.client.get(self.exam_url(exam))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'پایان یافته')
        self.assertFalse(ExamAttempt.objects.filter(student=self.student, exam=exam).exists())

    def test_ongoing_exam_is_enterable(self):
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        self.client.force_login(self.student)
        response = self.client.get(self.exam_url(exam))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EXAM_CONFIG')
        self.assertContains(response, hash_exam_id(exam.id))
        self.assertTrue(ExamAttempt.objects.filter(student=self.student, exam=exam).exists())

    def test_student_of_other_grade_is_denied(self):
        exam = self.make_exam(students=[self.student])
        outsider = make_student('outsider', grade=self.other_grade)
        exam.students.add(outsider)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(self.exam_url(exam)).status_code, 403)

    def test_non_enrolled_student_is_denied(self):
        exam = self.make_exam(students=[])
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.exam_url(exam)).status_code, 403)

    def test_tampered_hash_is_rejected(self):
        exam = self.make_exam()
        self.client.force_login(self.student)
        response = self.client.get(f'/student/exam/{exam.id}_deadbeefdeadbeef/')
        self.assertEqual(response.status_code, 404)

    def test_options_are_json_safe(self):
        """گزینه‌ها باید JSON باشند؛ وگرنه کوتیشن در متن گزینه صفحه را می‌شکست"""
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='multiple_choice',
                                max_score=Decimal('1'), order=1,
                                options=["گزینه با ' کوتیشن", 'دو', 'سه', 'چهار'])
        self.client.force_login(self.student)
        html = self.client.get(self.exam_url(exam)).content.decode()
        # آرایه گزینه‌ها باید JSON معتبر باشد (نه repr پایتون)
        marker = html.index('options: ')
        start = html.index('[', marker)
        depth = 0
        for end, ch in enumerate(html[start:], start):
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    break
        options = json.loads(html[start:end + 1])
        self.assertEqual(options[0], "گزینه با ' کوتیشن")


class SaveAnswerTests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.question = Question.objects.create(exam=self.exam, text='q', question_type='short_answer',
                                                max_score=Decimal('2'), order=1)
        self.client.force_login(self.student)

    def post_answer(self, payload):
        return self.client.post(reverse('save_answer'), data=json.dumps(payload),
                                content_type='application/json')

    def test_save_answer(self):
        response = self.post_answer({'question_id': self.question.id, 'answer_text': 'پاسخ'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(StudentAnswer.objects.get(question=self.question).answer_text, 'پاسخ')

    def test_unknown_question_returns_404_not_500(self):
        response = self.post_answer({'question_id': 999999, 'answer_text': 'x'})
        self.assertEqual(response.status_code, 404)

    def test_null_question_id_returns_404_not_500(self):
        response = self.post_answer({'question_id': None, 'answer_text': 'x'})
        self.assertEqual(response.status_code, 404)

    def test_malformed_json_returns_400(self):
        response = self.client.post(reverse('save_answer'), data='not-json', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_cannot_answer_after_submit(self):
        ExamAttempt.objects.create(student=self.student, exam=self.exam, status='submitted',
                                   started_at=self.now, submitted_at=self.now)
        response = self.post_answer({'question_id': self.question.id, 'answer_text': 'late'})
        self.assertEqual(response.status_code, 403)


class LogCheatTests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.client.force_login(self.student)

    def log(self, payload):
        return self.client.post(reverse('log_cheat'), data=json.dumps(payload),
                                content_type='application/json')

    def test_all_model_cheat_types_accepted(self):
        for cheat_type, _label in CheatAttempt.CHEAT_TYPES:
            with self.subTest(cheat_type=cheat_type):
                response = self.log({'exam_id': self.exam.id, 'cheat_type': cheat_type, 'detail': 'تست'})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['success'])
        self.assertEqual(CheatAttempt.objects.count(), len(CheatAttempt.CHEAT_TYPES))

    def test_invalid_cheat_type_rejected(self):
        response = self.log({'exam_id': self.exam.id, 'cheat_type': 'hacking'})
        self.assertFalse(response.json()['success'])

    def test_unknown_exam_returns_404(self):
        response = self.log({'exam_id': 999999, 'cheat_type': 'tab_switch'})
        self.assertEqual(response.status_code, 404)

    def test_non_json_detail_does_not_crash(self):
        response = self.log({'exam_id': self.exam.id, 'cheat_type': 'tab_switch', 'detail': 12345})
        self.assertEqual(response.status_code, 200)


class SemesterHelperTests(TestCase):
    def test_get_exam_semester_covers_winter_months(self):
        """قبلاً شرط «12 <= month <= 3» هیچ‌وقت درست نبود"""
        teacher = User.objects.create_user(username='t_s', password='x', role='teacher')
        grade = Grade.objects.create(name='7')
        for month, expected in [(7, 'first'), (9, 'first'), (11, 'first'),
                                (12, 'second'), (1, 'second'), (3, 'second'),
                                (6, 'final'), (4, 'final')]:
            exam = Exam(title=f'e{month}', teacher=teacher, grade=grade, duration_minutes=10,
                        start_time=timezone.make_aware(timezone.datetime(2026, month, 15, 8, 0)),
                        end_time=timezone.make_aware(timezone.datetime(2026, month, 15, 10, 0)))
            self.assertEqual(get_exam_semester(exam), expected, f'month={month}')

    def test_get_current_semester_is_never_empty(self):
        self.assertIn(get_current_semester(), ['اول', 'دوم', 'تابستان'])
