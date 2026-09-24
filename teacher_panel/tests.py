# -*- coding: utf-8 -*-
"""تست‌های پنل معلم: ساخت آزمون، سوالات، نمره‌دهی و API"""
import io
import json
from datetime import timedelta
from decimal import Decimal

import pandas as pd
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Grade, User
from exams.models import Exam, Question, StudentAnswer
from teacher_panel.views import to_jalali, parse_form_datetime, validate_exam_times


class TeacherPanelTestCase(TestCase):
    def setUp(self):
        self.grade = Grade.objects.create(name='9')
        self.teacher = User.objects.create_user(username='teacher_t', password='test12345', role='teacher')
        self.other_teacher = User.objects.create_user(username='teacher_o', password='test12345', role='teacher')
        self.student = User.objects.create_user(username='student_t', password='test12345',
                                                role='student', grade=self.grade)
        self.now = timezone.localtime(timezone.now())
        self.client.force_login(self.teacher)

    def create_exam_payload(self, **over):
        payload = {
            'title': 'آزمون تست',
            'grade': str(self.grade.id),
            'duration': '45',
            'start_time': (self.now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'),
            'end_time': (self.now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'timer_type': 'floating',
            'show_questions_mode': 'one_by_one',
            'show_score': 'on',
            'show_answers_after_exam': 'on',
            'enable_anti_cheat': 'on',
            'prevent_tab_switch': 'on',
            'prevent_copy_paste': 'on',
            'track_ip': 'on',
            'show_back_button': 'on',
            'allow_teacher_answer': 'on',
            'students': [str(self.student.id)],
        }
        payload.update(over)
        return payload

    def make_exam(self, **kw):
        exam = Exam.objects.create(
            title=kw.pop('title', 'آزمون'), teacher=self.teacher, grade=self.grade,
            duration_minutes=kw.pop('duration_minutes', 30),
            start_time=kw.pop('start_time', self.now - timedelta(minutes=5)),
            end_time=kw.pop('end_time', self.now + timedelta(hours=2)),
            **kw)
        exam.students.set([self.student])
        return exam


class CreateExamTests(TeacherPanelTestCase):
    def test_create_exam_saves_every_flag(self):
        response = self.client.post(reverse('create_exam'), self.create_exam_payload())
        self.assertEqual(response.status_code, 302)
        exam = Exam.objects.get(title='آزمون تست')
        self.assertEqual(exam.duration_minutes, 45)
        self.assertEqual(exam.students.count(), 1)
        self.assertTrue(exam.show_score_to_student)
        # این گزینه در فرم بود ولی قبلاً ذخیره نمی‌شد
        self.assertTrue(exam.show_answers_after_exam)
        self.assertTrue(exam.enable_anti_cheat and exam.prevent_tab_switch and exam.track_ip)
        self.assertTrue(timezone.is_aware(exam.start_time))

    def test_invalid_payloads_do_not_crash(self):
        bad_payloads = {
            'empty duration': self.create_exam_payload(duration=''),
            'junk duration': self.create_exam_payload(duration='abc'),
            'junk dates': self.create_exam_payload(start_time='not-a-date', end_time='nope'),
            'end before start': self.create_exam_payload(
                start_time=(self.now + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
                end_time=(self.now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')),
            'missing title': self.create_exam_payload(title='   '),
            'bad grade': self.create_exam_payload(grade='99999'),
            'empty form': {},
        }
        before = Exam.objects.count()
        for label, payload in bad_payloads.items():
            with self.subTest(case=label):
                response = self.client.post(reverse('create_exam'), payload)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'امکان ذخیره آزمون وجود ندارد')
        self.assertEqual(Exam.objects.count(), before, 'آزمون نامعتبری ساخته شد')

    def test_form_times_are_local_and_stable(self):
        """مقادیر فرم باید به وقت تهران باشند و با ذخیره مجدد جابه‌جا نشوند"""
        self.client.post(reverse('create_exam'), self.create_exam_payload())
        exam = Exam.objects.get(title='آزمون تست')
        expected_start = (self.now - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')

        html = self.client.get(reverse('edit_exam_info', kwargs={'exam_id': exam.id})).content.decode()
        self.assertIn(f'value="{expected_start}"', html, 'مقدار فیلد زمان شروع به وقت محلی نیست')
        self.assertIn(to_jalali(exam.start_time), html, 'معادل شمسی با ساعت محلی نمی‌خواند')

        # ذخیره مجدد همان مقادیر نباید ساعت را تغییر دهد
        start_before, end_before = exam.start_time, exam.end_time
        self.client.post(reverse('edit_exam_info', kwargs={'exam_id': exam.id}), {
            'save_info': '1', 'title': exam.title, 'grade': str(self.grade.id),
            'duration': str(exam.duration_minutes),
            'start_time': expected_start,
            'end_time': (self.now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'show_score': 'on', 'is_active': 'on',
        })
        exam.refresh_from_db()
        self.assertLess(abs((exam.start_time - start_before).total_seconds()), 60)
        self.assertLess(abs((exam.end_time - end_before).total_seconds()), 60)

    def test_edit_info_invalid_json_students(self):
        exam = self.make_exam()
        response = self.client.post(reverse('edit_exam_info', kwargs={'exam_id': exam.id}),
                                    {'save_students': '1', 'student_ids': 'not-json'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'error-msg')
        self.assertEqual(exam.students.count(), 1)


class QuestionTests(TeacherPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()

    def add(self, **payload):
        return self.client.post(reverse('add_question', kwargs={'exam_id': self.exam.id}), payload)

    def test_all_question_types_can_be_created(self):
        cases = {
            'multiple_choice': {'option_1': 'یک', 'option_2': 'دو', 'option_3': 'سه', 'option_4': 'چهار',
                                'options_type': 'text', 'correct_answer': '2'},
            'true_false': {'correct_answer': 'true'},
            'fill_blank': {'blanks': 'تهران, اصفهان', 'correct_answer': 'تهران'},
            'short_answer': {'correct_answer': 'کوتاه'},
            'long_answer': {'correct_answer': 'بلند'},
            'image_answer': {'allow_image_answer': 'on'},
            'matching': {'left_0': 'ایران', 'right_0': 'تهران', 'left_1': 'فرانسه', 'right_1': 'پاریس'},
        }
        for qtype, extra in cases.items():
            with self.subTest(qtype=qtype):
                payload = {'text': f'سوال {qtype}', 'question_type': qtype, 'max_score': '3.5'}
                payload.update(extra)
                self.assertEqual(self.add(**payload).status_code, 302)
        self.assertEqual(Question.objects.filter(exam=self.exam).count(), len(cases))
        self.assertEqual(Question.objects.get(exam=self.exam, question_type='fill_blank').blanks,
                         ['تهران', 'اصفهان'])
        self.assertEqual(len(Question.objects.get(exam=self.exam, question_type='matching').matching_pairs), 2)

    def test_invalid_question_type_is_rejected(self):
        response = self.add(text='بدون نوع', question_type='not_a_type', max_score='1')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Question.objects.filter(exam=self.exam).count(), 0)

    def test_zero_or_junk_score_is_rejected(self):
        self.add(text='q', question_type='short_answer', max_score='0')
        self.add(text='q', question_type='short_answer', max_score='abc')
        self.assertEqual(Question.objects.filter(exam=self.exam).count(), 0)

    def test_other_teacher_cannot_touch_exam(self):
        self.client.force_login(self.other_teacher)
        for url in [reverse('edit_exam', kwargs={'exam_id': self.exam.id}),
                    reverse('add_question', kwargs={'exam_id': self.exam.id})]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)


class GradingTests(TeacherPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()
        self.question = Question.objects.create(exam=self.exam, text='q', question_type='short_answer',
                                                max_score=Decimal('4'), order=1)
        self.answer = StudentAnswer.objects.create(student=self.student, question=self.question,
                                                   answer_text='پاسخ')

    def save(self, score):
        return self.client.post(reverse('save_score'), {'answer_id': str(self.answer.id), 'score': score})

    def test_score_is_saved(self):
        response = self.save('3.25')
        self.assertEqual(response.status_code, 200)
        self.answer.refresh_from_db()
        self.assertEqual(float(self.answer.score_obtained), 3.25)
        self.assertIsNotNone(self.answer.graded_by_id)
        self.assertIsNotNone(self.answer.graded_at)

    def test_score_is_clamped_to_max(self):
        """قبلاً نمره بیشتر از بارم سوال (مثلاً 999) ذخیره می‌شد"""
        self.save('999')
        self.answer.refresh_from_db()
        self.assertEqual(float(self.answer.score_obtained), 4.0)

    def test_negative_and_junk_scores_become_zero(self):
        for value in ['-5', 'abc', '']:
            with self.subTest(value=value):
                self.save(value)
                self.answer.refresh_from_db()
                self.assertEqual(float(self.answer.score_obtained), 0.0)

    def test_unknown_answer_returns_404(self):
        response = self.client.post(reverse('save_score'), {'answer_id': '999999', 'score': '1'})
        self.assertEqual(response.status_code, 404)

    def test_other_teacher_cannot_grade(self):
        self.client.force_login(self.other_teacher)
        response = self.save('2')
        self.assertEqual(response.status_code, 403)


class StudentsApiTests(TeacherPanelTestCase):
    def test_anonymous_is_blocked(self):
        self.client.logout()
        response = self.client.get(reverse('get_students_api'))
        self.assertIn(response.status_code, (302, 403))

    def test_student_is_blocked(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('get_students_api')).status_code, 403)

    def test_teacher_gets_json(self):
        response = self.client.get(reverse('get_students_api'))
        self.assertEqual(response.status_code, 200)
        names = [s['full_name'] for s in response.json()['students']]
        self.assertIn('student_t', names)


class ExcelTests(TeacherPanelTestCase):
    def setUp(self):
        super().setUp()
        self.exam = self.make_exam()

    def test_template_download_is_xlsx(self):
        response = self.client.get(reverse('download_question_template'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:2], b'PK')

    def test_bulk_upload(self):
        buf = io.BytesIO()
        pd.DataFrame([
            {'text': 'سوال ۱', 'question_type': 'تستی', 'max_score': 2,
             'option_1': 'الف', 'option_2': 'ب', 'option_3': 'ج', 'option_4': 'د', 'correct_answer': '1'},
            {'text': 'سوال ۲', 'question_type': 'صحیح/غلط', 'max_score': 1, 'correct_answer': 'true'},
            {'text': '', 'question_type': 'تستی', 'max_score': 1},
        ]).to_excel(buf, index=False)
        buf.seek(0)
        buf.name = 'questions.xlsx'

        response = self.client.post(reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}),
                                    {'excel_file': buf})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['success_count'], 2)
        self.assertEqual(data['skip_count'], 1, 'ردیف بدون متن باید نادیده گرفته شود')
        self.assertEqual(Question.objects.filter(exam=self.exam).count(), 2)
        # سلول خالی اکسل قبلاً به رشته «nan» تبدیل و به‌عنوان متن سوال ذخیره می‌شد
        self.assertFalse(Question.objects.filter(text__icontains='nan').exists())
        # شماره ترتیب باید پشت سر هم باشد (قبلاً ۱،۳،۵,... می‌شد)
        self.assertEqual(sorted(Question.objects.filter(exam=self.exam)
                                .values_list('order', flat=True)), [1, 2])
        self.assertEqual(Question.objects.get(exam=self.exam, order=2).question_type, 'true_false')

    def test_new_question_after_import_goes_to_the_end(self):
        """قبلاً با count()+1 سوال جدید وسط سوالات ایمپورت‌شده قرار می‌گرفت"""
        buf = io.BytesIO()
        pd.DataFrame([
            {'text': 'سوال ۱', 'question_type': 'تستی', 'max_score': 1, 'correct_answer': '1'},
            {'text': 'سوال ۲', 'question_type': 'تستی', 'max_score': 1, 'correct_answer': '2'},
            {'text': 'سوال ۳', 'question_type': 'تستی', 'max_score': 1, 'correct_answer': '3'},
        ]).to_excel(buf, index=False)
        buf.seek(0)
        buf.name = 'q.xlsx'
        self.client.post(reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}),
                         {'excel_file': buf})

        self.client.post(reverse('add_question', kwargs={'exam_id': self.exam.id}),
                         {'text': 'سوال دستی', 'question_type': 'short_answer', 'max_score': '1'})
        orders = list(Question.objects.filter(exam=self.exam).order_by('order')
                      .values_list('text', flat=True))
        self.assertEqual(orders[-1], 'سوال دستی', orders)
        self.assertEqual(len(set(Question.objects.filter(exam=self.exam)
                                 .values_list('order', flat=True))), 4, 'order تکراری ساخته شد')

    def test_bulk_upload_rejects_bad_file(self):
        buf = io.BytesIO(b'not an excel')
        buf.name = 'fake.xlsx'
        response = self.client.post(reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}),
                                    {'excel_file': buf})
        self.assertEqual(response.status_code, 400)

    def test_bulk_upload_requires_file(self):
        response = self.client.post(reverse('bulk_upload_questions', kwargs={'exam_id': self.exam.id}), {})
        self.assertEqual(response.status_code, 400)


class HelperTests(TeacherPanelTestCase):
    def test_to_jalali_uses_local_timezone(self):
        """ساعت نمایشی باید وقت تهران باشد نه UTC"""
        aware = timezone.now()
        rendered = to_jalali(aware)
        local = timezone.localtime(aware)
        self.assertTrue(rendered.endswith(local.strftime('%H:%M')), f'{rendered} != {local:%H:%M}')

    def test_to_jalali_handles_bad_input(self):
        self.assertEqual(to_jalali(None), '')
        self.assertEqual(to_jalali('not-a-date'), '')

    def test_parse_form_datetime(self):
        parsed = parse_form_datetime('2026-09-20T10:30')
        self.assertTrue(timezone.is_aware(parsed))
        self.assertEqual(timezone.localtime(parsed).strftime('%Y-%m-%dT%H:%M'), '2026-09-20T10:30')
        self.assertIsNone(parse_form_datetime('junk'))
        self.assertIsNone(parse_form_datetime(''))

    def test_validate_exam_times(self):
        data, errors = validate_exam_times(self.create_exam_payload())
        self.assertEqual(errors, [])
        self.assertTrue(data['show_score_to_student'] and data['show_answers_after_exam'])

        data, errors = validate_exam_times({'title': 'x'})
        self.assertTrue(errors)


class FillBlankGradingTests(TeacherPanelTestCase):
    """پاسخ جاخالی به‌صورت «مقدار۱ | مقدار۲» ذخیره می‌شود و باید خوانا نمایش داده شود"""

    def make(self, blanks, correct, answer):
        exam = Exam.objects.create(title='fb', teacher=self.teacher, grade=self.grade,
                                   duration_minutes=20, start_time=self.now - timedelta(hours=1),
                                   end_time=self.now + timedelta(hours=1))
        exam.students.set([self.student])
        q = Question.objects.create(exam=exam, text='جاهای خالی', question_type='fill_blank',
                                    blanks=blanks, correct_answer=correct,
                                    max_score=Decimal('2'), order=1)
        StudentAnswer.objects.create(student=self.student, question=q, answer_text=answer)
        return exam, q

    def test_is_correct_helper(self):
        from teacher_panel.views import fill_blank_is_correct
        self.assertTrue(fill_blank_is_correct('تهران | مشهد', 'تهران, مشهد'))
        self.assertTrue(fill_blank_is_correct('تهران|مشهد', 'تهران ، مشهد'))
        self.assertFalse(fill_blank_is_correct('تهران | ', 'تهران, مشهد'))
        self.assertFalse(fill_blank_is_correct('شیراز | مشهد', 'تهران, مشهد'))
        self.assertTrue(fill_blank_is_correct('تهران', 'تهران'))
        self.assertFalse(fill_blank_is_correct('', 'تهران'))
        self.assertFalse(fill_blank_is_correct('تهران', ''))

    def test_grade_page_shows_readable_blanks(self):
        exam, _q = self.make(['پایتخت', 'بزرگترین شهر'], 'تهران, مشهد', 'تهران | مشهد')
        res = self.client.get(reverse('grade_exam', kwargs={'exam_id': exam.id}))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('پایتخت: تهران', html)
        self.assertIn('بزرگترین شهر: مشهد', html)


class TeacherFeaturesTests(TestCase):
    """امکانات جدید: تصحیح خودکار، کپی آزمون، خروجی CSV، تحلیل سوال‌ها"""

    def setUp(self):
        from accounts.models import User, Grade
        from exams.models import Exam, Question
        import datetime
        from django.utils import timezone
        self.teacher = User.objects.create_user(username='t1', password='test12345', role='teacher')
        grade = Grade.objects.first() or Grade.objects.create(name='7')
        self.student = User.objects.create_user(username='s1', password='test12345', role='student', grade=grade)
        now = timezone.now()
        self.exam = Exam.objects.create(
            teacher=self.teacher, grade=grade, title='آزمون ویژگی‌ها',
            duration_minutes=10, start_time=now - datetime.timedelta(hours=1),
            end_time=now + datetime.timedelta(hours=1))
        self.exam.students.add(self.student)
        self.q_mc = Question.objects.create(exam=self.exam, question_type='multiple_choice',
                                              text='سوال تستی', options=['الف', 'ب'], correct_answer='2',
                                              max_score=2, order=1)
        self.q_tf = Question.objects.create(exam=self.exam, question_type='true_false',
                                              text='سوال صحیح غلط', correct_answer='true', max_score=1, order=2)
        self.q_blank = Question.objects.create(exam=self.exam, question_type='fill_blank',
                                               text='جاخالی', correct_answer='تهران', max_score=1, order=3)
        self.q_match = Question.objects.create(
            exam=self.exam, question_type='matching', text='وصل کن',
            matching_pairs=[{'left': 'a', 'right': '1'}, {'left': 'b', 'right': '2'}],
            max_score=2, order=4)
        self.q_match.correct_answer = json.dumps({
            'pair_%d_0' % self.q_match.id: 'pair_%d_0' % self.q_match.id,
            'pair_%d_1' % self.q_match.id: 'pair_%d_1' % self.q_match.id})
        self.q_match.save()
        self.q_long = Question.objects.create(exam=self.exam, question_type='long_answer',
                                              text='تشریحی', max_score=4, order=5)

    def _answer(self, q, text):
        from exams.models import StudentAnswer
        return StudentAnswer.objects.create(student=self.student, question=q, answer_text=text)

    def test_auto_grade_attempt_scores_objective(self):
        from exams.grading import auto_grade_attempt
        from exams.models import StudentAnswer
        self._answer(self.q_mc, '2')      # صحیح
        self._answer(self.q_tf, 'false')  # غلط
        self._answer(self.q_blank, ' تهران ')  # صحیح با فاصله
        self._answer(self.q_match, json.dumps({'pair_%d_0' % self.q_match.id: 'pair_%d_0' % self.q_match.id,
                                               'pair_%d_1' % self.q_match.id: 'pair_%d_1' % self.q_match.id}))
        self._answer(self.q_long, 'متن تشریحی')
        n = auto_grade_attempt(self.student, self.exam)
        self.assertEqual(n, 4)
        self.assertEqual(float(StudentAnswer.objects.get(question=self.q_mc).score_obtained), 2.0)
        self.assertEqual(float(StudentAnswer.objects.get(question=self.q_tf).score_obtained), 0.0)
        self.assertEqual(float(StudentAnswer.objects.get(question=self.q_blank).score_obtained), 1.0)
        self.assertTrue(StudentAnswer.objects.get(question=self.q_mc).auto_graded)
        self.assertIsNone(StudentAnswer.objects.get(question=self.q_long).score_obtained)

    def test_auto_grade_respects_manual_score(self):
        from exams.grading import auto_grade_attempt
        a = self._answer(self.q_mc, '1')  # غلط ولی معلم نمره دستی داده
        a.score_obtained = 2.0
        a.graded_by = self.teacher
        a.save()
        auto_grade_attempt(self.student, self.exam)
        a.refresh_from_db()
        self.assertEqual(float(a.score_obtained), 2.0)

    def test_duplicate_exam(self):
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('duplicate_exam', args=[self.exam.id]))
        self.assertEqual(r.status_code, 302)
        from exams.models import Exam
        copy = Exam.objects.filter(teacher=self.teacher).exclude(id=self.exam.id).first()
        self.assertIsNotNone(copy)
        self.assertIn('(کپی)', copy.title)
        self.assertFalse(copy.is_active)
        self.assertEqual(copy.questions.count(), 5)
        self.assertEqual(copy.students.count(), 1)

    def test_export_results_csv(self):
        self.client.login(username='t1', password='test12345')
        r = self.client.get(reverse('export_results_csv', args=[self.exam.id]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        body = b''.join(r.streaming_content) if hasattr(r, 'streaming_content') else r.content
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))  # BOM فارسی
        text = body.decode('utf-8-sig')
        self.assertIn('نام دانش‌آموز', text)
        self.assertIn('s1', text)

    def test_results_page_has_analysis(self):
        self.client.login(username='t1', password='test12345')
        self._answer(self.q_mc, '2')
        r = self.client.get(reverse('exam_results', args=[self.exam.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'تحلیل سوال‌به‌سوال')


class BankGroupsAnnounceTests(TestCase):
    """بانک سوال، گروه‌های دانش‌آموزی و اطلاعیه‌ها"""

    def setUp(self):
        from accounts.models import User, Grade
        from exams.models import Exam
        import datetime
        from django.utils import timezone
        self.teacher = User.objects.create_user(username='t1', password='test12345', role='teacher')
        self.other = User.objects.create_user(username='t2', password='test12345', role='teacher')
        self.grade = Grade.objects.first() or Grade.objects.create(name='7')
        self.s1 = User.objects.create_user(username='s1', password='test12345', role='student', grade=self.grade)
        self.s2 = User.objects.create_user(username='s2', password='test12345', role='student', grade=self.grade)
        now = timezone.now()
        self.exam = Exam.objects.create(
            teacher=self.teacher, grade=self.grade, title='آزمون بانک',
            duration_minutes=10, start_time=now - datetime.timedelta(hours=1),
            end_time=now + datetime.timedelta(hours=1))

    def test_bank_add_import_delete(self):
        from exams.models import QuestionBank
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('question_bank'), {
            'text': 'سوال بانکی تستی', 'question_type': 'multiple_choice',
            'options': 'الف\nب', 'correct_answer': '1', 'max_score': '2'})
        self.assertEqual(r.status_code, 302)
        bank = QuestionBank.objects.get(teacher=self.teacher)
        self.assertEqual(bank.options, ['الف', 'ب'])
        r = self.client.post(reverse('import_bank_question', args=[bank.id]), {'exam_id': self.exam.id})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.exam.questions.count(), 1)
        q = self.exam.questions.first()
        self.assertEqual(q.options, ['الف', 'ب'])
        self.assertEqual(float(q.max_score), 2.0)
        bank.refresh_from_db()
        self.assertEqual(bank.use_count, 1)
        r = self.client.post(reverse('delete_bank_question', args=[bank.id]))
        self.assertEqual(QuestionBank.objects.count(), 0)

    def test_save_to_bank_checkbox_on_add_question(self):
        from exams.models import QuestionBank
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('add_question', args=[self.exam.id]), {
            'text': 'سوال جدید', 'question_type': 'true_false', 'max_score': '1',
            'correct_answer': 'true', 'save_to_bank': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(QuestionBank.objects.filter(teacher=self.teacher).count(), 1)

    def test_group_create_and_apply(self):
        from exams.models import StudentGroup
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('groups'), {
            'action': 'create', 'name': 'کلاس الف', 'students': [str(self.s1.id), str(self.s2.id)]})
        self.assertEqual(r.status_code, 302)
        g = StudentGroup.objects.get(teacher=self.teacher)
        self.assertEqual(g.students.count(), 2)
        r = self.client.post(reverse('apply_group_to_exam', args=[self.exam.id]), {'group_id': g.id})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.exam.students.count(), 2)

    def test_group_of_other_teacher_not_applicable(self):
        from exams.models import StudentGroup
        g = StudentGroup.objects.create(teacher=self.other, name='گروه غریبه')
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('apply_group_to_exam', args=[self.exam.id]), {'group_id': g.id})
        self.assertEqual(r.status_code, 404)

    def test_announcement_visible_to_student_and_delete_guard(self):
        from exams.models import Announcement
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('announcement_create'), {
            'title': 'جلسه رفع اشکال', 'body': 'پنجشنبه ساعت ۱۷', 'back': 'teacher_dashboard'})
        self.assertEqual(r.status_code, 302)
        ann = Announcement.objects.get()
        self.client.logout()
        self.client.login(username='s1', password='test12345')
        r = self.client.get(reverse('student_dashboard'))
        self.assertContains(r, 'جلسه رفع اشکال')
        # دانش‌آموز نمی‌تواند حذف کند
        r = self.client.post(reverse('announcement_delete', args=[ann.id]))
        self.assertEqual(r.status_code, 403)
        # معلم دیگر هم نمی‌تواند
        self.client.logout()
        self.client.login(username='t2', password='test12345')
        r = self.client.post(reverse('announcement_delete', args=[ann.id]))
        self.assertEqual(r.status_code, 403)
        # نویسنده می‌تواند
        self.client.logout()
        self.client.login(username='t1', password='test12345')
        r = self.client.post(reverse('announcement_delete', args=[ann.id]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Announcement.objects.count(), 0)


class BankFolderTests(TestCase):
    """پوشه‌بندی بانک سوال: ساخت، تغییر نام، حذف، جابجایی و فیلتر"""

    def setUp(self):
        from accounts.models import User
        from exams.models import QuestionBank
        self.teacher = User.objects.create_user(username='tf', password='test12345', role='teacher')
        self.other = User.objects.create_user(username='of', password='test12345', role='teacher')
        self.client.login(username='tf', password='test12345')
        self.q = QuestionBank.objects.create(teacher=self.teacher, text='سوال نمونه',
                                               question_type='multiple_choice',
                                               options=['۱', '۲'], correct_answer='1')

    def _folder(self, name='پوشه یک', teacher=None):
        from exams.models import BankFolder
        return BankFolder.objects.create(teacher=teacher or self.teacher, name=name)

    def test_add_folder_and_duplicate_rejected(self):
        r = self.client.post('/teacher/bank/folder/add/', {'name': 'ریاضی'})
        self.assertEqual(r.status_code, 302)
        from exams.models import BankFolder
        self.assertTrue(BankFolder.objects.filter(teacher=self.teacher, name='ریاضی').exists())
        self.client.post('/teacher/bank/folder/add/', {'name': 'ریاضی'})
        self.assertEqual(BankFolder.objects.filter(teacher=self.teacher, name='ریاضی').count(), 1)

    def test_add_question_into_folder_and_filter(self):
        f = self._folder()
        r = self.client.post('/teacher/bank/', {'text': 'سوال داخل پوشه', 'question_type': 'short_answer',
                                                'correct_answer': 'پاسخ مورد انتظار',
                                                'folder': str(f.id)})
        self.assertEqual(r.status_code, 302)
        from exams.models import QuestionBank
        q = QuestionBank.objects.get(text='سوال داخل پوشه')
        self.assertEqual(q.folder_id, f.id)
        resp = self.client.get(f'/teacher/bank/?folder={f.id}')
        self.assertContains(resp, 'سوال داخل پوشه')
        self.assertNotContains(resp, 'سوال نمونه')
        resp = self.client.get('/teacher/bank/?folder=none')
        self.assertContains(resp, 'سوال نمونه')

    def test_rename_folder(self):
        f = self._folder()
        self.client.post(f'/teacher/bank/folder/{f.id}/rename/', {'name': 'فیزیک'})
        f.refresh_from_db()
        self.assertEqual(f.name, 'فیزیک')

    def test_delete_folder_keeps_questions(self):
        f = self._folder()
        self.q.folder = f
        self.q.save()
        self.client.post(f'/teacher/bank/folder/{f.id}/delete/')
        self.q.refresh_from_db()
        self.assertIsNone(self.q.folder_id)

    def test_move_question_between_folders(self):
        f1, f2 = self._folder('الف'), self._folder('ب')
        self.client.post(f'/teacher/bank/{self.q.id}/move/', {'folder': str(f1.id)})
        self.q.refresh_from_db()
        self.assertEqual(self.q.folder_id, f1.id)
        self.client.post(f'/teacher/bank/{self.q.id}/move/', {'folder': ''})
        self.q.refresh_from_db()
        self.assertIsNone(self.q.folder_id)

    def test_other_teacher_folder_is_404(self):
        f = self._folder(teacher=self.other)
        for url in (f'/teacher/bank/folder/{f.id}/rename/', f'/teacher/bank/folder/{f.id}/delete/'):
            self.assertEqual(self.client.post(url, {'name': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(f'/teacher/bank/{self.q.id}/move/', {'folder': str(f.id)}).status_code, 404)


class BankDynamicFormTests(TestCase):
    """فرم پویای بانک سوال: فیلدهای نوع‌محور، اعتبارسنجی، ویرایش و دکمهٔ «سوال بعدی»"""

    def setUp(self):
        from accounts.models import User
        self.teacher = User.objects.create_user(username='td', password='test12345', role='teacher')
        self.other = User.objects.create_user(username='od', password='test12345', role='teacher')
        self.client.login(username='td', password='test12345')

    def _add(self, **kw):
        data = {'text': 'صورت سوال', 'question_type': 'multiple_choice',
                'option1': 'الف', 'option2': 'ب', 'correct_answer': '1'}
        data.update(kw)
        return self.client.post(reverse('question_bank'), data)

    def _bank(self):
        from exams.models import QuestionBank
        return QuestionBank.objects.get(teacher=self.teacher)

    def test_mc_saved_from_option_fields(self):
        r = self._add(option3='ج', correct_answer='2', max_score='2.5')
        self.assertEqual(r.status_code, 302)
        b = self._bank()
        self.assertEqual(b.options, ['الف', 'ب', 'ج'])
        self.assertEqual(b.correct_answer, '2')
        self.assertEqual(str(b.max_score), '2.50')

    def test_legacy_options_textarea_still_works(self):
        r = self.client.post(reverse('question_bank'), {
            'text': 'سوال قدیمی', 'question_type': 'multiple_choice',
            'options': 'الف\nب', 'correct_answer': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._bank().options, ['الف', 'ب'])

    def test_mc_needs_two_options(self):
        r = self._add(option2='')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'حداقل دو گزینه')
        from exams.models import QuestionBank
        self.assertFalse(QuestionBank.objects.exists())

    def test_mc_wrong_correct_index_rejected(self):
        r = self._add(correct_answer='9')
        self.assertEqual(r.status_code, 200)
        from exams.models import QuestionBank
        self.assertFalse(QuestionBank.objects.exists())

    def test_true_false_saves_only_answer(self):
        r = self._add(question_type='true_false', correct_answer='false',
                      option1='الف', option2='ب')
        self.assertEqual(r.status_code, 302)
        b = self._bank()
        self.assertEqual(b.options, [])
        self.assertEqual(b.correct_answer, 'false')

    def test_true_false_requires_answer(self):
        r = self._add(question_type='true_false', correct_answer='')
        self.assertEqual(r.status_code, 200)
        from exams.models import QuestionBank
        self.assertFalse(QuestionBank.objects.exists())

    def test_fill_blank_requires_answers_and_keeps_blanks(self):
        r = self._add(question_type='fill_blank', blanks='پایتخت, بزرگ‌ترین شهر', correct_answer='')
        self.assertEqual(r.status_code, 200)
        r = self._add(question_type='fill_blank', blanks='پایتخت, بزرگ‌ترین شهر',
                      correct_answer='تهران, مشهد')
        self.assertEqual(r.status_code, 302)
        b = self._bank()
        self.assertEqual(b.blanks, ['پایتخت', 'بزرگ‌ترین شهر'])
        self.assertEqual(b.correct_answer, 'تهران, مشهد')
        self.assertEqual(b.options, [])

    def test_short_answer_requires_expected(self):
        r = self._add(question_type='short_answer', correct_answer='')
        self.assertEqual(r.status_code, 200)
        r = self._add(question_type='short_answer', correct_answer='جرم تقسیم بر حجم')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._bank().correct_answer, 'جرم تقسیم بر حجم')

    def test_stay_button_reopens_form(self):
        r = self._add(stay='1')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('?new=1'))

    def test_edit_updates_all_fields(self):
        self._add()
        b = self._bank()
        r = self.client.post(reverse('bank_question_edit', args=[b.id]), {
            'text': 'صورت ویرایش‌شده', 'question_type': 'true_false', 'correct_answer': 'true',
            'max_score': '3', 'folder': ''})
        self.assertEqual(r.status_code, 302)
        b.refresh_from_db()
        self.assertEqual(b.text, 'صورت ویرایش‌شده')
        self.assertEqual(b.question_type, 'true_false')
        self.assertEqual(b.correct_answer, 'true')
        self.assertEqual(b.options, [])
        self.assertEqual(str(b.max_score), '3.00')

    def test_edit_validation_error_reopens_edit_form(self):
        self._add()
        b = self._bank()
        r = self.client.post(reverse('bank_question_edit', args=[b.id]), {
            'text': 'متن', 'question_type': 'multiple_choice', 'option1': 'تنها',
            'correct_answer': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertIn('?edit=%d' % b.id, r.url)
        b.refresh_from_db()
        self.assertEqual(b.text, 'صورت سوال')

    def test_edit_other_teacher_is_404(self):
        from exams.models import QuestionBank
        q = QuestionBank.objects.create(teacher=self.other, text='مال دیگری',
                                        question_type='true_false', correct_answer='true')
        r = self.client.post(reverse('bank_question_edit', args=[q.id]),
                             {'text': 'هک', 'question_type': 'true_false', 'correct_answer': 'true'})
        self.assertEqual(r.status_code, 404)


class BankTreeTests(TestCase):
    """بانک سوال درختی: زیرپوشه، فیلتر نوادگان، حذف/جابجایی پوشه، عملیات گروهی، بانک نمونه"""

    def setUp(self):
        from accounts.models import User
        from exams.models import Exam, BankFolder, QuestionBank
        from django.utils import timezone
        from accounts.models import Grade
        grade, _ = Grade.objects.get_or_create(name='7')
        self.t = User.objects.create_user(username='tt', password='test12345', role='teacher')
        self.o = User.objects.create_user(username='oo', password='test12345', role='teacher')
        self.client.login(username='tt', password='test12345')
        self.root = BankFolder.objects.create(teacher=self.t, name='ریاضی')
        self.child = BankFolder.objects.create(teacher=self.t, name='فصل ۱', parent=self.root)
        self.q1 = QuestionBank.objects.create(teacher=self.t, text='سوال ریشه', question_type='short_answer',
                                              correct_answer='x', folder=self.root)
        self.q2 = QuestionBank.objects.create(teacher=self.t, text='سوال فرزند', question_type='true_false',
                                              correct_answer='true', folder=self.child, difficulty='hard')
        now = timezone.now()
        self.exam = Exam.objects.create(teacher=self.t, title='آزمون', grade=grade, duration_minutes=30,
                                        start_time=now, end_time=now + timezone.timedelta(hours=1))

    def test_subfolder_create_and_same_name_in_other_parent(self):
        from exams.models import BankFolder
        self.client.post('/teacher/bank/folder/add/', {'name': 'فصل ۱', 'parent': ''})
        self.assertEqual(BankFolder.objects.filter(teacher=self.t, name='فصل ۱').count(), 2)
        self.client.post('/teacher/bank/folder/add/', {'name': 'فصل ۱', 'parent': str(self.root.id)})
        self.assertEqual(BankFolder.objects.filter(teacher=self.t, name='فصل ۱').count(), 2)

    def test_parent_filter_includes_descendants(self):
        r = self.client.get(f'/teacher/bank/?folder={self.root.id}')
        self.assertContains(r, 'سوال ریشه')
        self.assertContains(r, 'سوال فرزند')
        r = self.client.get(f'/teacher/bank/?folder={self.child.id}')
        self.assertNotContains(r, 'سوال ریشه')

    def test_search_and_filters(self):
        r = self.client.get('/teacher/bank/?q=فرزند')
        self.assertContains(r, 'سوال فرزند')
        self.assertNotContains(r, 'سوال ریشه')
        r = self.client.get('/teacher/bank/?difficulty=hard')
        self.assertNotContains(r, 'سوال ریشه')
        r = self.client.get('/teacher/bank/?type=short_answer')
        self.assertNotContains(r, 'سوال فرزند')

    def test_cannot_move_folder_into_descendant(self):
        self.client.post(f'/teacher/bank/folder/{self.root.id}/rename/',
                         {'name': 'ریاضی', 'parent': str(self.child.id)})
        self.root.refresh_from_db()
        self.assertIsNone(self.root.parent_id)

    def test_delete_folder_moves_children_to_parent(self):
        self.client.post(f'/teacher/bank/folder/{self.root.id}/delete/')
        self.child.refresh_from_db()
        self.q1.refresh_from_db()
        self.assertIsNone(self.child.parent_id)
        self.assertIsNone(self.q1.folder_id)

    def test_folder_import_to_exam(self):
        self.client.post(f'/teacher/bank/folder/{self.root.id}/import/', {'exam_id': self.exam.id})
        self.assertEqual(self.exam.questions.count(), 2)

    def test_bulk_actions(self):
        from exams.models import QuestionBank
        ids = [self.q1.id, self.q2.id]
        self.client.post('/teacher/bank/bulk/', {'ids': ids, 'action': 'move', 'folder': ''})
        self.assertEqual(QuestionBank.objects.filter(folder__isnull=True).count(), 2)
        self.client.post('/teacher/bank/bulk/', {'ids': ids, 'action': 'import', 'exam_id': self.exam.id})
        self.assertEqual(self.exam.questions.count(), 2)
        self.client.post('/teacher/bank/bulk/', {'ids': ids, 'action': 'delete'})
        self.assertFalse(QuestionBank.objects.filter(teacher=self.t).exists())

    def test_bulk_ignores_other_teacher_questions(self):
        from exams.models import QuestionBank
        other_q = QuestionBank.objects.create(teacher=self.o, text='مال دیگری', question_type='short_answer',
                                              correct_answer='x')
        self.client.post('/teacher/bank/bulk/', {'ids': [other_q.id], 'action': 'delete'})
        self.assertTrue(QuestionBank.objects.filter(id=other_q.id).exists())

    def test_seed_sample_bank_idempotent(self):
        from exams.models import QuestionBank
        from exams.bank_seed import iter_bank
        before = QuestionBank.objects.filter(teacher=self.t).count()
        self.client.post('/teacher/bank/seed-sample/')
        n = QuestionBank.objects.filter(teacher=self.t).count()
        self.assertEqual(n - before, sum(1 for _ in iter_bank()))
        self.client.post('/teacher/bank/seed-sample/')
        self.assertEqual(QuestionBank.objects.filter(teacher=self.t).count(), n)
        # همهٔ انواع سوال موجود است و پاسخ تستی معتبر است
        types = set(QuestionBank.objects.filter(teacher=self.t).values_list('question_type', flat=True))
        self.assertEqual(types, {'multiple_choice', 'true_false', 'fill_blank', 'short_answer', 'long_answer'})
        for b in QuestionBank.objects.filter(teacher=self.t, question_type='multiple_choice'):
            self.assertTrue(1 <= int(b.correct_answer) <= len(b.options))
        for b in QuestionBank.objects.filter(teacher=self.t, question_type='fill_blank'):
            self.assertEqual(len(b.blanks), len(b.correct_answer.split(',')), b.text)
        self.assertEqual(self.client.get('/teacher/bank/').status_code, 200)
