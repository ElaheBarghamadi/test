# -*- coding: utf-8 -*-
"""تست‌های پنل دانش‌آموز: داشبورد، ورود به آزمون، ذخیره پاسخ و ثبت تخلف"""
import html as html_module
import json
import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Grade, User
from exams.models import (Exam, Question, StudentAnswer, ExamAttempt, CheatAttempt,
                          ExamSession, TeacherAnswer)
from student_panel.views import hash_exam_id, get_exam_semester, get_current_semester


html_unescape = html_module.unescape


def extract_data_attr(html, attr_name):
    """استخراج مقدار یک صفت data-... از اولین کارت سوال"""
    match = re.search(attr_name + r'="([^"]*)"', html)
    if not match:
        raise AssertionError(f'{attr_name} در صفحه پیدا نشد')
    return match.group(1)


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
        # گزینه‌ها داخل data-options به‌صورت JSON معتبر (و HTML-escape شده) قرار می‌گیرند
        attr = extract_data_attr(html, 'data-options')
        options = json.loads(html_unescape(attr))
        self.assertEqual(options[0], "گزینه با ' کوتیشن")
        self.assertNotIn('options: [', html.replace('data-options', ''))


class SaveAnswerTests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.question = Question.objects.create(exam=self.exam, text='q', question_type='short_answer',
                                                max_score=Decimal('2'), order=1)
        self.client.force_login(self.student)
        self.client.get(self.exam_url(self.exam))  # شروع آزمون (ساخت attempt)

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
        attempt = ExamAttempt.objects.get(student=self.student, exam=self.exam)
        attempt.status = 'submitted'
        attempt.submitted_at = self.now
        attempt.save()
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


class TakeExamSettingsTests(StudentPanelTestCase):
    """صفحه آزمون باید دقیقاً طبق تنظیمات معلم رندر شود"""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    def page(self, exam):
        return self.client.get(self.exam_url(exam)).content.decode()

    def test_all_teacher_settings_reach_the_page(self):
        exam = self.make_exam(
            show_questions_mode='all', show_back_button=False, random_questions=True,
            enable_anti_cheat=False, prevent_tab_switch=True, prevent_copy_paste=False,
            timer_type='fixed', track_ip=False,
        )
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        html = self.page(exam)
        self.assertIn('showMode: "all"', html)
        self.assertIn('showBackBtn: false', html)
        self.assertIn('randomQuestions: true', html)
        self.assertIn('antiCheat: false', html)
        self.assertIn('preventTab: true', html)
        self.assertIn('preventCopy: false', html)
        self.assertIn('timerType: "fixed"', html)
        self.assertIn('trackIp: false', html)
        self.assertIn('class="mode-all timer-fixed', html)

    def test_anti_cheat_notice_only_when_enabled(self):
        on = self.make_exam(title='on', enable_anti_cheat=True)
        off = self.make_exam(title='off', enable_anti_cheat=False)
        for exam in (on, off):
            Question.objects.create(exam=exam, text='q', question_type='true_false',
                                    max_score=Decimal('1'), order=1)
        self.assertIn('حالت محافظت از آزمون فعال است', self.page(on))
        self.assertNotIn('حالت محافظت از آزمون فعال است', self.page(off))

    def test_image_options_type_is_passed(self):
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='multiple_choice',
                                options_type='image', max_score=Decimal('1'), order=1,
                                options=['/media/a.png', '/media/b.png'])
        html = self.page(exam)
        self.assertIn('data-otype="image"', html)
        self.assertIn('/media/a.png', html)

    def test_fill_blank_inputs_count_and_labels(self):
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='fill_blank',
                                blanks=['پایتخت ایران', 'بزرگترین شهر'], correct_answer='تهران, مشهد',
                                max_score=Decimal('2'), order=1)
        html = self.page(exam)
        self.assertIn('data-blankscount="2"', html)
        self.assertIn('پایتخت ایران', html_unescape(extract_data_attr(html, 'data-blanks')))

    def test_fill_blank_labels_hidden_when_they_are_the_answers(self):
        """اگر معلم پاسخ‌ها را در فیلد جاهای خالی نوشته باشد، نباید به دانش‌آموز نشان داده شود"""
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='fill_blank',
                                blanks=['تهران', 'مشهد'], correct_answer='تهران, مشهد',
                                max_score=Decimal('2'), order=1)
        html = self.page(exam)
        self.assertIn('data-blankscount="2"', html)
        self.assertEqual(json.loads(html_unescape(extract_data_attr(html, 'data-blanks'))), ['', ''])
        self.assertNotIn('تهران', html_unescape(extract_data_attr(html, 'data-blanks')))

    def test_matching_pairs_have_stable_ids(self):
        exam = self.make_exam()
        Question.objects.create(exam=exam, text='q', question_type='matching',
                                matching_pairs=[{'left': 'a', 'right': '1'}, {'left': 'b', 'right': '2'}],
                                max_score=Decimal('2'), order=1)
        html = self.page(exam)
        pairs = json.loads(html_unescape(extract_data_attr(html, 'data-pairs')))
        self.assertEqual(pairs[0]['left'], 'a')

    def test_track_ip_creates_session(self):
        exam = self.make_exam(track_ip=True)
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        self.page(exam)
        session = ExamSession.objects.filter(student=self.student, exam=exam).first()
        self.assertIsNotNone(session)
        self.assertTrue(session.ip_address)
        self.assertTrue(session.is_active)

    def test_track_ip_disabled_creates_no_session(self):
        exam = self.make_exam(track_ip=False)
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        self.page(exam)
        self.assertFalse(ExamSession.objects.filter(student=self.student, exam=exam).exists())

    def test_ip_change_logged_as_cheat_when_anti_cheat_on(self):
        exam = self.make_exam(track_ip=True, enable_anti_cheat=True)
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        self.client.get(self.exam_url(exam), REMOTE_ADDR='1.2.3.4')
        self.client.get(self.exam_url(exam), REMOTE_ADDR='5.6.7.8')
        self.assertEqual(ExamSession.objects.filter(exam=exam).count(), 1)
        self.assertTrue(CheatAttempt.objects.filter(session__exam=exam, cheat_type='different_ip').exists())

    def test_empty_exam_shows_notice_not_crash(self):
        exam = self.make_exam()
        html = self.page(exam)
        self.assertIn('این آزمون هنوز سوالی ندارد', html)

    def test_saved_answers_embedded_as_json_script(self):
        exam = self.make_exam()
        q = Question.objects.create(exam=exam, text='q', question_type='short_answer',
                                    max_score=Decimal('1'), order=1)
        StudentAnswer.objects.create(student=self.student, question=q, answer_text='پاسخ قبلی')
        html = self.page(exam)
        blob = re.search(r'<script id="savedAnswersData"[^>]*>(.*?)</script>', html, re.S)
        self.assertIsNotNone(blob, 'json_script پاسخ‌های ذخیره‌شده در صفحه نیست')
        data = json.loads(blob.group(1))
        self.assertEqual(data[str(q.id)]['answer_text'], 'پاسخ قبلی')


class SaveAnswerV2Tests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.client.force_login(self.student)
        self.client.get(self.exam_url(self.exam))  # شروع آزمون (ساخت attempt)

    def post(self, payload):
        return self.client.post(reverse('save_answer'), data=json.dumps(payload),
                                content_type='application/json')

    def test_fill_blank_blanks_are_joined(self):
        q = Question.objects.create(exam=self.exam, text='q', question_type='fill_blank',
                                    blanks=['a', 'b'], max_score=Decimal('2'), order=1)
        res = self.post({'question_id': q.id, 'blanks': ['تهران', 'مشهد']})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(StudentAnswer.objects.get(question=q).answer_text, 'تهران | مشهد')

    def test_fill_blank_partial_answer_keeps_positions(self):
        q = Question.objects.create(exam=self.exam, text='q', question_type='fill_blank',
                                    blanks=['a', 'b', 'c'], max_score=Decimal('3'), order=1)
        self.post({'question_id': q.id, 'blanks': ['تهران', '', 'شیراز']})
        self.assertEqual(StudentAnswer.objects.get(question=q).answer_text, 'تهران |  | شیراز')

    def test_null_answer_text_does_not_wipe_existing(self):
        q = Question.objects.create(exam=self.exam, text='q', question_type='image_answer',
                                    max_score=Decimal('2'), order=1, allow_image_answer=True)
        StudentAnswer.objects.create(student=self.student, question=q, answer_text='توضیح من')
        res = self.post({'question_id': q.id, 'answer_text': None})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(StudentAnswer.objects.get(question=q).answer_text, 'توضیح من')

    def test_expired_fixed_exam_rejects_save(self):
        exam = self.make_exam(title='late', timer_type='fixed',
                              start=self.now - timedelta(hours=3), end=self.now - timedelta(minutes=30))
        q = Question.objects.create(exam=exam, text='q', question_type='short_answer',
                                    max_score=Decimal('1'), order=1)
        ExamAttempt.objects.create(student=self.student, exam=exam, status='in_progress',
                                   started_at=self.now - timedelta(hours=2))
        res = self.post({'question_id': q.id, 'answer_text': 'دیر رسید'})
        self.assertEqual(res.status_code, 403)

    def test_grace_period_allows_final_save(self):
        exam = self.make_exam(title='grace', timer_type='fixed',
                              start=self.now - timedelta(hours=1), end=self.now - timedelta(seconds=20))
        q = Question.objects.create(exam=exam, text='q', question_type='short_answer',
                                    max_score=Decimal('1'), order=1)
        ExamAttempt.objects.create(student=self.student, exam=exam, status='in_progress',
                                   started_at=self.now - timedelta(minutes=50))
        res = self.post({'question_id': q.id, 'answer_text': 'آخرین پاسخ'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(StudentAnswer.objects.get(question=q).answer_text, 'آخرین پاسخ')

    def test_oversized_answer_rejected(self):
        q = Question.objects.create(exam=self.exam, text='q', question_type='long_answer',
                                    max_score=Decimal('1'), order=1)
        res = self.post({'question_id': q.id, 'answer_text': 'x' * 10001})
        self.assertEqual(res.status_code, 400)

    def test_non_string_answer_rejected(self):
        q = Question.objects.create(exam=self.exam, text='q', question_type='long_answer',
                                    max_score=Decimal('1'), order=1)
        res = self.post({'question_id': q.id, 'answer_text': {'a': 1}})
        self.assertEqual(res.status_code, 400)


class SaveAllAnswersTests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.q1 = Question.objects.create(exam=self.exam, text='q1', question_type='short_answer',
                                          max_score=Decimal('1'), order=1)
        self.q2 = Question.objects.create(exam=self.exam, text='q2', question_type='fill_blank',
                                          blanks=['a', 'b'], max_score=Decimal('2'), order=2)
        self.client.force_login(self.student)
        self.client.get(self.exam_url(self.exam))  # شروع آزمون (ساخت attempt)

    def post(self, payload):
        return self.client.post(reverse('save_all_answers'), data=json.dumps(payload),
                                content_type='application/json')

    def test_saves_multiple_answers_at_once(self):
        res = self.post({'exam_id': self.exam.id, 'answers': {
            str(self.q1.id): {'answer_text': 'پاسخ یک'},
            str(self.q2.id): {'blanks': ['تهران', 'مشهد']},
        }})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['saved'], 2)
        self.assertEqual(StudentAnswer.objects.get(question=self.q1).answer_text, 'پاسخ یک')
        self.assertEqual(StudentAnswer.objects.get(question=self.q2).answer_text, 'تهران | مشهد')

    def test_plain_string_values_supported(self):
        res = self.post({'exam_id': self.exam.id, 'answers': {str(self.q1.id): 'ساده'}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(StudentAnswer.objects.get(question=self.q1).answer_text, 'ساده')

    def test_unknown_exam_404(self):
        self.assertEqual(self.post({'exam_id': 999999, 'answers': {}}).status_code, 404)

    def test_other_exam_question_ignored(self):
        other = self.make_exam(title='other')
        q = Question.objects.create(exam=other, text='q', question_type='short_answer',
                                    max_score=Decimal('1'), order=1)
        res = self.post({'exam_id': self.exam.id, 'answers': {str(q.id): {'answer_text': 'hack'}}})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['failed'], 1)
        self.assertFalse(StudentAnswer.objects.filter(question=q).exists())

    def test_non_enrolled_student_rejected(self):
        outsider = make_student('outsider_sa', grade=self.grade)
        self.client.force_login(outsider)
        res = self.post({'exam_id': self.exam.id, 'answers': {str(self.q1.id): 'x'}})
        self.assertEqual(res.status_code, 403)


class SubmitExamPostTests(StudentPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.q = Question.objects.create(exam=self.exam, text='q', question_type='short_answer',
                                         max_score=Decimal('1'), order=1)
        self.client.force_login(self.student)
        self.client.get(self.exam_url(self.exam))  # ساخت attempt
        self.url = self.exam_url(self.exam, view='submit_exam')

    def post(self, payload=None):
        return self.client.post(self.url, data=json.dumps(payload or {}),
                                content_type='application/json')

    def test_post_saves_answers_and_submits(self):
        res = self.post({'answers': {str(self.q.id): {'answer_text': 'پاسخ نهایی'}}})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('/student/thanks/', data['redirect'])
        attempt = ExamAttempt.objects.get(student=self.student, exam=self.exam)
        self.assertEqual(attempt.status, 'submitted')
        self.assertIsNotNone(attempt.submitted_at)
        self.assertEqual(StudentAnswer.objects.get(question=self.q).answer_text, 'پاسخ نهایی')

    def test_post_twice_is_idempotent(self):
        self.post({'answers': {}})
        res = self.post({'answers': {str(self.q.id): {'answer_text': 'بعد از ثبت'}}})
        self.assertTrue(res.json().get('already_submitted'))
        self.assertFalse(StudentAnswer.objects.filter(question=self.q).exists())

    def test_get_still_redirects(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(ExamAttempt.objects.get(exam=self.exam).status, 'submitted')

    def test_submit_closes_tracking_session(self):
        exam = self.make_exam(title='tracked', track_ip=True)
        Question.objects.create(exam=exam, text='q', question_type='true_false',
                                max_score=Decimal('1'), order=1)
        self.client.get(self.exam_url(exam))
        self.assertTrue(ExamSession.objects.get(exam=exam).is_active)
        self.client.post(self.exam_url(exam, view='submit_exam'), data=json.dumps({}),
                         content_type='application/json')
        self.assertFalse(ExamSession.objects.get(exam=exam).is_active)

    def test_malformed_json_does_not_crash(self):
        res = self.client.post(self.url, data='not-json', content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])


class ExamResultSettingsTests(StudentPanelTestCase):
    """کارنامه باید دقیقاً تابع show_score_to_student و show_answers_after_exam باشد"""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.student)

    def prepare(self, show_score, show_answers):
        exam = self.make_exam(show_score_to_student=show_score,
                              show_answers_after_exam=show_answers)
        q = Question.objects.create(exam=exam, text='پایتخت ایران کدام است؟',
                                    question_type='multiple_choice',
                                    options=['تهران', 'شیراز', 'تبریز', 'مشهد'],
                                    correct_answer='1', max_score=Decimal('2'), order=1)
        ExamAttempt.objects.create(student=self.student, exam=exam, status='submitted',
                                   started_at=self.now, submitted_at=self.now)
        StudentAnswer.objects.create(student=self.student, question=q, answer_text='2',
                                     score_obtained=0)
        return exam, q

    def get(self, exam):
        return self.client.get(reverse('exam_result_detail', kwargs={'exam_id': exam.id}))

    def test_both_off_redirects(self):
        exam, _q = self.prepare(False, False)
        self.assertEqual(self.get(exam).status_code, 302)

    def test_score_off_answers_on(self):
        exam, _q = self.prepare(False, True)
        res = self.get(exam)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'نمایش نمره برای این آزمون توسط معلم غیرفعال شده است')
        self.assertContains(res, 'پاسخ صحیح')
        self.assertContains(res, 'گزینه 1: تهران')
        self.assertNotContains(res, 'id="scoreSummary"')

    def test_score_on_answers_off_does_not_leak(self):
        exam, _q = self.prepare(True, False)
        res = self.get(exam)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="scoreSummary"')
        self.assertNotContains(res, 'پاسخ صحیح')
        self.assertNotContains(res, 'گزینه 1: تهران')

    def test_correct_answer_rendered_for_all_types(self):
        exam = self.make_exam(show_score_to_student=True, show_answers_after_exam=True)
        specs = [
            ('true_false', {'correct_answer': 'false'}, '❌ غلط'),
            ('multiple_choice', {'options': ['الف', 'ب'], 'correct_answer': '2'}, 'گزینه 2: ب'),
            ('fill_blank', {'blanks': ['پایتخت', 'بزرگترین شهر'],
                            'correct_answer': 'تهران, مشهد'}, 'پایتخت: تهران'),
            ('short_answer', {'correct_answer': 'پاسخ نمونه'}, 'پاسخ نمونه'),
        ]
        for i, (qtype, extra, expected) in enumerate(specs, start=1):
            Question.objects.create(exam=exam, text=f'q{i}', question_type=qtype,
                                    max_score=Decimal('1'), order=i, **extra)
        matching = Question.objects.create(
            exam=exam, text='q5', question_type='matching', max_score=Decimal('1'), order=5,
            matching_pairs=[{'left': 'ایران', 'right': 'تهران'}, {'left': 'فرانسه', 'right': 'پاریس'}])
        matching.correct_answer = json.dumps({f'pair_{matching.id}_0': 'r_0',
                                              f'pair_{matching.id}_1': 'r_1'})
        matching.save()

        ExamAttempt.objects.create(student=self.student, exam=exam, status='submitted',
                                   started_at=self.now, submitted_at=self.now)
        html = self.get(exam).content.decode()
        for expected in ['❌ غلط', 'گزینه 2: ب', 'پایتخت: تهران', 'بزرگترین شهر: مشهد',
                         'پاسخ نمونه', 'ایران ← تهران', 'فرانسه ← پاریس']:
            self.assertIn(expected, html)

    def test_teacher_answer_shown_when_available(self):
        exam, q = self.prepare(True, True)
        TeacherAnswer.objects.create(question=q, answer_text='توضیح کامل معلم')
        self.assertContains(self.get(exam), 'توضیح کامل معلم')
        self.assertContains(self.get(exam), 'پاسخ تشریحی معلم')
