# teacher_panel/views.py
# -*- coding: utf-8 -*-

# ========== ایمپورت‌های پایه ==========
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.core.files.storage import default_storage
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied

# ========== ایمپورت‌های مدل‌ها ==========
from exams.models import (
    Exam, Question, StudentAnswer, ExamAttempt,
    ExamSession, CheatAttempt, ExamLog, TeacherAnswer
)
from accounts.models import User, Grade

# ========== ایمپورت‌های جانبی ==========
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
import jdatetime


# ========== توابع کمکی ==========
def to_jalali(date_val):
    """تبدیل تاریخ میلادی به شمسی"""
    if not date_val:
        return ''
    try:
        if isinstance(date_val, str):
            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        if timezone.is_naive(date_val):
            date_val = timezone.make_aware(date_val)
        jd = jdatetime.datetime.fromgregorian(datetime=date_val)
        return jd.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def check_teacher_access(user, exam=None):
    """بررسی دسترسی معلم به آزمون"""
    if user.role != 'teacher':
        raise PermissionDenied('شما دسترسی معلم ندارید')
    if exam and exam.teacher != user:
        raise PermissionDenied('شما به این آزمون دسترسی ندارید')
    return True


def validate_decimal_score(value, max_value=None):
    """اعتبارسنجی و گرد کردن نمره"""
    try:
        score = Decimal(str(value))
        score = round(score, 2)
        if score < 0:
            score = Decimal('0.00')
        if max_value and score > Decimal(str(max_value)):
            score = Decimal(str(max_value))
        return score
    except:
        return Decimal('0.00')


# ========== ویوهای داشبورد ==========
@login_required
def teacher_dashboard(request):
    """داشبورد معلم - لیست آزمون‌ها با وضعیت"""
    if request.user.role != 'teacher':
        return redirect('/')

    exams = Exam.objects.filter(teacher=request.user).annotate(
        students_count=Count('students')
    )

    now = timezone.now()
    exams_with_status = []
    active_count = ongoing_count = inactive_count = 0

    for exam in exams:
        if not exam.is_active:
            status_data = ('inactive', 'غیرفعال', 'status-inactive', 'inactive')
            inactive_count += 1
        elif exam.start_time <= now <= exam.end_time:
            status_data = ('ongoing', 'در حال برگزاری', 'status-ongoing', 'ongoing')
            ongoing_count += 1
            active_count += 1
        elif exam.end_time < now:
            status_data = ('ended', 'تمام شده', 'status-ended', '')
            active_count += 1
        else:
            status_data = ('active', 'فعال', 'status-active', 'active')
            active_count += 1

        exam.status, exam.status_text, exam.status_badge_class, exam.status_class = status_data
        exams_with_status.append(exam)

    return render(request, 'teacher_panel/dashboard.html', {
        'exams': exams_with_status,
        'grades': Grade.objects.all(),
        'active_exams_count': active_count,
        'ongoing_exams_count': ongoing_count,
        'inactive_exams_count': inactive_count,
        'total_students': User.objects.filter(role='student').count(),
    })


# ========== مدیریت آزمون ==========
@login_required
def create_exam(request):
    """ساخت آزمون جدید"""
    check_teacher_access(request.user)

    if request.method == 'POST':
        exam = Exam.objects.create(
            title=request.POST.get('title', '').strip(),
            teacher=request.user,
            grade_id=request.POST.get('grade'),
            duration_minutes=int(request.POST.get('duration', 0)),
            start_time=request.POST.get('start_time'),
            end_time=request.POST.get('end_time'),
            show_score_to_student='show_score' in request.POST,
            enable_anti_cheat='enable_anti_cheat' in request.POST,
            prevent_tab_switch='prevent_tab_switch' in request.POST,
            prevent_copy_paste='prevent_copy_paste' in request.POST,
            track_ip='track_ip' in request.POST,
            show_questions_mode=request.POST.get('show_questions_mode', 'one_by_one'),
            show_back_button='show_back_button' in request.POST,
            allow_teacher_answer='allow_teacher_answer' in request.POST,
            timer_type=request.POST.get('timer_type', 'floating'),
        )
        exam.students.set(request.POST.getlist('students'))
        return redirect('edit_exam', exam_id=exam.id)

    now = timezone.now()
    return render(request, 'teacher_panel/create_exam.html', {
        'grades': Grade.objects.all(),
        'students': User.objects.filter(role='student'),
        'default_start': now.strftime('%Y-%m-%dT%H:%M'),
        'default_end': (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
        'start_jalali': to_jalali(now),
        'end_jalali': to_jalali(now + timedelta(hours=2)),
    })


@login_required
def edit_exam_info(request, exam_id):
    """مدیریت اطلاعات آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    success_msg = None

    def format_datetime(dt):
        if not dt:
            return ''
        try:
            return dt.strftime('%Y-%m-%dT%H:%M')
        except:
            return ''

    if request.method == 'POST':
        if 'save_info' in request.POST:
            exam.title = request.POST.get('title', '').strip()
            exam.grade_id = request.POST.get('grade')
            exam.duration_minutes = int(request.POST.get('duration', 0))
            exam.start_time = request.POST.get('start_time')
            exam.end_time = request.POST.get('end_time')
            exam.show_score_to_student = 'show_score' in request.POST
            exam.is_active = 'is_active' in request.POST
            exam.save()
            success_msg = 'اطلاعات آزمون با موفقیت ذخیره شد'

        elif 'save_settings' in request.POST:
            exam.random_questions = 'random_questions' in request.POST
            exam.show_questions_mode = request.POST.get('show_questions_mode', 'one_by_one')
            exam.show_back_button = 'show_back_button' in request.POST
            exam.enable_anti_cheat = 'enable_anti_cheat' in request.POST
            exam.prevent_tab_switch = 'prevent_tab_switch' in request.POST
            exam.prevent_copy_paste = 'prevent_copy_paste' in request.POST
            exam.track_ip = 'track_ip' in request.POST
            exam.allow_teacher_answer = 'allow_teacher_answer' in request.POST
            exam.show_answers_after_exam = 'show_answers_after_exam' in request.POST
            exam.timer_type = request.POST.get('timer_type', 'floating')
            exam.save()
            success_msg = 'تنظیمات آزمون با موفقیت ذخیره شد'

        elif 'save_students' in request.POST:
            student_ids = json.loads(request.POST.get('student_ids', '[]'))
            exam.students.set(student_ids)
            success_msg = f'لیست دانش‌آموزان با موفقیت ذخیره شد ({len(student_ids)} نفر)'

    # آمار تخلفات
    cheats = CheatAttempt.objects.filter(session__exam=exam)
    cheats_stats = {
        'total_cheats': cheats.count(),
        'tab_switch': cheats.filter(cheat_type='tab_switch').count(),
        'copy_paste': cheats.filter(cheat_type='copy_paste').count(),
        'multiple_tabs': cheats.filter(cheat_type='multiple_tabs').count(),
    }

    return render(request, 'teacher_panel/edit_exam_info.html', {
        'exam': exam,
        'grades': Grade.objects.all(),
        'all_students': User.objects.filter(role='student'),
        'students': exam.students.all(),
        'selected_student_ids': json.dumps(list(exam.students.values_list('id', flat=True))),
        'success_msg': success_msg,
        'start_jalali': to_jalali(exam.start_time),
        'end_jalali': to_jalali(exam.end_time),
        'start_miladi': format_datetime(exam.start_time),
        'end_miladi': format_datetime(exam.end_time),
        'cheats_stats': cheats_stats,
        'recent_cheats': [
            {
                'student_name': c.session.student.get_full_name() or c.session.student.username,
                'cheat_type_display': c.get_cheat_type_display(),
                'detail': c.detail,
                'created_at': c.created_at,
            }
            for c in cheats.select_related('session__student').order_by('-created_at')[:10]
        ],
    })


@login_required
def edit_exam(request, exam_id):
    """ویرایش سوالات آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    questions = exam.questions.all().order_by('order')
    cheats = CheatAttempt.objects.filter(session__exam=exam)

    return render(request, 'teacher_panel/edit_exam.html', {
        'exam': exam,
        'questions': questions,
        'cheats_stats': {
            'total_cheats': cheats.count(),
            'tab_switch': cheats.filter(cheat_type='tab_switch').count(),
            'copy_paste': cheats.filter(cheat_type='copy_paste').count(),
            'multiple_tabs': cheats.filter(cheat_type='multiple_tabs').count(),
        },
        'recent_cheats': [
            {
                'student_name': c.session.student.get_full_name() or c.session.student.username,
                'cheat_type_display': c.get_cheat_type_display(),
                'detail': c.detail,
                'created_at': c.created_at,
            }
            for c in cheats.select_related('session__student').order_by('-created_at')[:10]
        ],
        'questions_with_teacher_answer': [
            {'question': q, 'answer_text': ta.answer_text, 'answer_image': ta.answer_image}
            for q in questions
            for ta in [TeacherAnswer.objects.filter(question=q).first()]
            if ta and ta.answer_text
        ],
    })


@login_required
def delete_exam(request, exam_id):
    """حذف آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    exam.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    messages.success(request, 'آزمون با موفقیت حذف شد')
    return redirect('teacher_dashboard')


@login_required
def toggle_exam_status(request, exam_id):
    """فعال/غیرفعال کردن آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    exam.is_active = not exam.is_active
    exam.save()
    return redirect('teacher_dashboard')


# ========== مدیریت سوالات ==========
@login_required
def add_question(request, exam_id):
    """افزودن سوال جدید"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    if request.method == 'POST':
        max_score = validate_decimal_score(request.POST.get('max_score', 0))

        question = Question.objects.create(
            exam=exam,
            text=request.POST.get('text', '').strip(),
            question_type=request.POST.get('question_type'),
            max_score=max_score,
            order=exam.questions.count() + 1,
            allow_image_answer='allow_image_answer' in request.POST,
        )

        if 'image' in request.FILES:
            question.image = request.FILES['image']

        q_type = request.POST.get('question_type')

        if q_type == 'multiple_choice':
            options = [request.POST.get(f'option_{i}', f'گزینه {i}') for i in range(1, 5)]
            question.options = options
            question.options_type = request.POST.get('options_type', 'text')
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'true_false':
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'fill_blank':
            blanks = request.POST.get('blanks', '').split(',')
            question.blanks = [b.strip() for b in blanks if b.strip()]
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type in ['short_answer', 'long_answer']:
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'matching':
            pairs = []
            i = 0
            while True:
                left = request.POST.get(f'left_{i}')
                right = request.POST.get(f'right_{i}')
                if left or right:
                    pairs.append({'left': left or '', 'right': right or ''})
                    i += 1
                else:
                    break
            question.matching_pairs = pairs

        question.save()
        return redirect('edit_exam', exam_id=exam.id)

    return render(request, 'teacher_panel/add_question.html', {'exam': exam})


@login_required
def edit_question(request, exam_id, question_id):
    """ویرایش سوال"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    question = get_object_or_404(Question, id=question_id, exam=exam)
    check_teacher_access(request.user, exam)

    if request.method == 'POST':
        question.text = request.POST.get('text', '').strip()
        question.question_type = request.POST.get('question_type')
        question.max_score = validate_decimal_score(request.POST.get('max_score', 0))
        question.allow_image_answer = 'allow_image_answer' in request.POST

        if 'remove_image' in request.POST and question.image:
            question.image.delete(save=False)
            question.image = None

        if 'image' in request.FILES:
            question.image = request.FILES['image']

        q_type = request.POST.get('question_type')
        correct_val = request.POST.get('correct_answer', '')

        if q_type == 'multiple_choice':
            options = [request.POST.get(f'option_{i}', f'گزینه {i}') for i in range(1, 5)]
            question.options = options
            question.options_type = request.POST.get('options_type', 'text')
            question.correct_answer = correct_val

        elif q_type == 'true_false':
            question.correct_answer = correct_val

        elif q_type == 'fill_blank':
            blanks = request.POST.get('blanks', '').split(',')
            question.blanks = [b.strip() for b in blanks if b.strip()]
            question.correct_answer = correct_val

        elif q_type in ['short_answer', 'long_answer']:
            question.correct_answer = correct_val

        elif q_type == 'matching':
            pairs = []
            i = 0
            while True:
                left = request.POST.get(f'left_{i}')
                right = request.POST.get(f'right_{i}')
                if left or right:
                    pairs.append({'left': left or '', 'right': right or ''})
                    i += 1
                else:
                    break
            question.matching_pairs = pairs

        question.save()
        return redirect('edit_exam', exam_id=exam.id)

    return render(request, 'teacher_panel/edit_question.html', {
        'exam': exam,
        'question': question,
    })


@login_required
def delete_question(request, exam_id, question_id):
    """حذف سوال"""
    question = get_object_or_404(Question, id=question_id, exam__teacher=request.user)
    question.delete()
    return redirect('edit_exam', exam_id=exam_id)


# ========== تصحیح و نمره‌دهی ==========
@login_required
def grade_exam(request, exam_id):
    """صفحه تصحیح دستی آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    questions = exam.questions.all().order_by('order')
    students = exam.students.filter(grade=exam.grade)

    questions_with_answers = []
    for question in questions:
        answers_list = []
        for student in students:
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            if not answer:
                answer = StudentAnswer.objects.create(
                    student=student,
                    question=question,
                    answer_text='',
                    score_obtained=Decimal('0.00')
                )

            is_correct = False
            if answer.answer_text and question.correct_answer:
                if question.question_type in ['true_false', 'multiple_choice', 'fill_blank']:
                    is_correct = (answer.answer_text.strip().lower() == question.correct_answer.strip().lower())

            # ========== تبدیل پاسخ matching به متن خوانا ==========
            answer_display = answer.answer_text

            if question.question_type == 'matching' and answer.answer_text:
                try:
                    selections = json.loads(answer.answer_text)
                    matching_pairs = question.matching_pairs or []

                    display_lines = []

                    for i, pair in enumerate(matching_pairs):
                        left = pair.get('left', '')

                        key = f"pair_{question.id}_{i}"
                        selected_value = selections.get(key)

                        if selected_value:
                            try:
                                selected_idx = int(str(selected_value).split('_')[-1])

                                if 0 <= selected_idx < len(matching_pairs):
                                    right = matching_pairs[selected_idx].get('right', '')
                                    display_lines.append(
                                        f"🔹 {left} ←→ {right}"
                                    )
                                else:
                                    display_lines.append(
                                        f"🔹 {left} ←→ ❌ گزینه نامعتبر"
                                    )

                            except Exception:
                                display_lines.append(
                                    f"🔹 {left} ←→ ❌ خطا"
                                )
                        else:
                            display_lines.append(
                                f"🔹 {left} ←→ ❌ انتخاب نشده"
                            )

                    answer_display = "\n".join(display_lines)

                except Exception as e:
                    answer_display = (
                        f"⚠️ خطا در نمایش پاسخ\n"
                        f"{answer.answer_text}"
                    )
            # ========== تبدیل پاسخ صحیح معلم برای matching ==========
            correct_answer_display = question.correct_answer

            if question.question_type == 'matching' and question.correct_answer:
                try:
                    correct_selections = json.loads(question.correct_answer)
                    matching_pairs = question.matching_pairs or []

                    correct_lines = []

                    for i, pair in enumerate(matching_pairs):
                        left = pair.get('left', '')

                        key = f"pair_{question.id}_{i}"
                        selected_value = correct_selections.get(key)

                        if selected_value:
                            try:
                                selected_idx = int(str(selected_value).split('_')[-1])

                                if 0 <= selected_idx < len(matching_pairs):
                                    right = matching_pairs[selected_idx].get('right', '')
                                    correct_lines.append(
                                        f"🔹 {left} ←→ {right}"
                                    )
                                else:
                                    correct_lines.append(
                                        f"🔹 {left} ←→ ❌ گزینه نامعتبر"
                                    )

                            except Exception:
                                correct_lines.append(
                                    f"🔹 {left} ←→ ❌ خطا"
                                )
                        else:
                            correct_lines.append(
                                f"🔹 {left} ←→ ❌ تعریف نشده"
                            )

                    correct_answer_display = "\n".join(correct_lines)

                except Exception as e:
                    correct_answer_display = (
                        f"⚠️ خطا در نمایش پاسخ صحیح\n"
                        f"{question.correct_answer}"
                    )

            answers_list.append({
                'student': student,
                'answer_text': answer_display,  # ← نمایش خوانا برای دانش‌آموز
                'answer_raw': answer.answer_text,  # ← نگهداری نسخه خام برای ذخیره
                'answer_image': answer.answer_image.url if answer.answer_image else None,
                'answer_id': answer.id,
                'score': float(answer.score_obtained) if answer.score_obtained is not None else None,
                'is_correct': is_correct,
            })

        questions_with_answers.append({
            'id': question.id,
            'text': question.text,
            'question_type': question.question_type,
            'max_score': float(question.max_score),
            'answers_data': answers_list,
            'correct_answer': correct_answer_display,  # ← نمایش خوانا برای پاسخ صحیح
            'correct_answer_raw': question.correct_answer,
            'matching_pairs': question.matching_pairs,
        })

    return render(request, 'teacher_panel/grade_exam.html', {
        'exam': exam,
        'questions': questions_with_answers,
        'students': students,
        'grades': Grade.objects.all(),
    })


@require_http_methods(["POST"])
@login_required
def save_score(request):
    """ذخیره نمره برای یک پاسخ (AJAX)"""
    answer_id = request.POST.get('answer_id')
    score = validate_decimal_score(request.POST.get('score', 0))

    answer = get_object_or_404(StudentAnswer, id=answer_id)

    # بررسی دسترسی معلم به این پاسخ
    if answer.question.exam.teacher != request.user:
        return JsonResponse({'success': False, 'error': 'شما به این پاسخ دسترسی ندارید'})

    answer.score_obtained = score
    answer.graded_by = request.user
    answer.graded_at = timezone.now()
    answer.save()

    return JsonResponse({'success': True, 'score': float(score)})


@require_http_methods(["POST"])
@login_required
def save_student_score(request, exam_id, student_id, question_id):
    """ذخیره نمره برای یک سوال خاص (AJAX)"""
    data = json.loads(request.body)
    score = validate_decimal_score(data.get('score', 0))

    answer = StudentAnswer.objects.filter(
        student_id=student_id,
        question_id=question_id,
        question__exam_id=exam_id,
    ).first()

    if not answer:
        return JsonResponse({'success': False, 'error': 'پاسخ یافت نشد'})

    # بررسی دسترسی معلم
    if answer.question.exam.teacher != request.user:
        return JsonResponse({'success': False, 'error': 'شما به این پاسخ دسترسی ندارید'})

    answer.score_obtained = score
    answer.graded_by = request.user
    answer.graded_at = timezone.now()
    answer.save()

    return JsonResponse({'success': True, 'score': float(score)})


@login_required
def view_student_answers(request, exam_id):
    """مشاهده پاسخ‌های دانش‌آموزان"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    attempts = ExamAttempt.objects.filter(exam=exam, status='submitted').select_related('student')
    questions = exam.questions.all().order_by('order')

    students_data = []
    for attempt in attempts:
        student = attempt.student
        answers_data = []
        total_score = Decimal('0.00')
        total_possible = Decimal('0.00')

        for question in questions:
            student_answer = StudentAnswer.objects.filter(student=student, question=question).first()

            # ✅ تبدیل امن به Decimal
            if student_answer and student_answer.score_obtained is not None:
                score = Decimal(str(student_answer.score_obtained))
            else:
                score = Decimal('0.00')

            total_score += score
            total_possible += question.max_score  # question.max_score از نوع Decimal است

            answers_data.append({
                'question': question,
                'answer': student_answer,
                'score': float(score),
                'max_score': float(question.max_score),
                'teacher_answer': TeacherAnswer.objects.filter(question=question).first(),
                'is_correct': score == question.max_score,
            })

        # محاسبه درصد با تبدیل به float
        total_score_float = float(total_score)
        total_possible_float = float(total_possible)
        percentage = (total_score_float / total_possible_float * 100) if total_possible_float > 0 else 0

        students_data.append({
            'student': student,
            'attempt': attempt,
            'answers': answers_data,
            'total_score': total_score_float,
            'total_possible': total_possible_float,
            'percentage': round(percentage, 1),
        })

    students_data.sort(key=lambda x: x['total_score'], reverse=True)

    return render(request, 'teacher_panel/view_student_answers.html', {
        'exam': exam,
        'students_data': students_data,
        'questions': questions,
    })


@login_required
def exam_results(request, exam_id):
    """نمایش نتایج نهایی آزمون"""
    from decimal import Decimal

    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    results = []
    for student in exam.students.filter(grade=exam.grade):
        total_score = Decimal('0.00')
        total_possible = Decimal('0.00')
        answered_questions = 0

        for question in exam.questions.all():
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            total_possible += Decimal(str(question.max_score))

            if answer and answer.score_obtained is not None:
                # تبدیل به Decimal برای جلوگیری از خطای TypeError
                total_score += Decimal(str(answer.score_obtained))
                answered_questions += 1

        # محاسبه درصد با استفاده از Decimal
        if total_possible > 0:
            percentage = float((total_score / total_possible) * Decimal('100'))
        else:
            percentage = 0

        results.append({
            'student': student,
            'total_score': float(total_score),
            'total_possible': float(total_possible),
            'percentage': round(percentage, 1),
            'answered_count': answered_questions,
            'total_questions': exam.questions.count(),
        })

    results.sort(key=lambda x: x['total_score'], reverse=True)

    # محاسبه آمار با بررسی وجود نتایج
    if results:
        avg_score = sum(r['total_score'] for r in results) / len(results)
        highest = max(r['total_score'] for r in results)
        lowest = min(r['total_score'] for r in results)
        fully_graded = sum(1 for r in results if r['answered_count'] == r['total_questions'])
    else:
        avg_score = 0
        highest = 0
        lowest = 0
        fully_graded = 0

    return render(request, 'teacher_panel/exam_results.html', {
        'exam': exam,
        'results': results,
        'stats': {
            'average_score': round(avg_score, 2),
            'highest_score': highest,
            'lowest_score': lowest,
            'total_students': len(results),
            'fully_graded': fully_graded,
        },
    })

# ========== پاسخ تشریحی معلم ==========
@login_required
def add_teacher_answer(request, exam_id, question_id):
    """افزودن/ویرایش پاسخ تشریحی معلم"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    question = get_object_or_404(Question, id=question_id, exam=exam)
    check_teacher_access(request.user, exam)

    if request.method == 'POST':
        teacher_answer, _ = TeacherAnswer.objects.get_or_create(question=question)
        teacher_answer.answer_text = request.POST.get('answer_text', '')

        if 'answer_image' in request.FILES:
            if teacher_answer.answer_image:
                teacher_answer.answer_image.delete()
            teacher_answer.answer_image = request.FILES['answer_image']

        if 'remove_image' in request.POST and teacher_answer.answer_image:
            teacher_answer.answer_image.delete()
            teacher_answer.answer_image = None

        teacher_answer.save()
        messages.success(request, 'پاسخ تشریحی با موفقیت ذخیره شد.')
        return redirect('edit_exam', exam_id=exam.id)

    return render(request, 'teacher_panel/add_teacher_answer.html', {
        'exam': exam,
        'question': question,
        'teacher_answer': TeacherAnswer.objects.filter(question=question).first(),
    })


@login_required
def exam_settings(request, exam_id):
    """تنظیمات آزمون (امنیت، نمایش سوالات و ...)"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)

    if request.method == 'POST':
        # تنظیمات امنیتی
        exam.enable_anti_cheat = 'enable_anti_cheat' in request.POST
        exam.prevent_tab_switch = 'prevent_tab_switch' in request.POST
        exam.prevent_copy_paste = 'prevent_copy_paste' in request.POST
        exam.track_ip = 'track_ip' in request.POST

        # تنظیمات نمایش سوالات
        exam.show_questions_mode = request.POST.get('show_questions_mode', 'one_by_one')
        exam.show_back_button = 'show_back_button' in request.POST

        # تنظیمات پاسخ تشریحی
        exam.allow_teacher_answer = 'allow_teacher_answer' in request.POST
        exam.show_answers_after_exam = 'show_answers_after_exam' in request.POST
        exam.show_score_to_student = 'show_score_to_student' in request.POST

        exam.save()
        messages.success(request, 'تنظیمات آزمون با موفقیت ذخیره شد.')
        return redirect('exam_settings', exam_id=exam.id)

    return render(request, 'teacher_panel/exam_settings.html', {'exam': exam})


# ========== گزارش تخلفات ==========
@login_required
def exam_cheats_report(request, exam_id):
    """گزارش تخلفات آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    sessions = ExamSession.objects.filter(exam=exam).select_related('student')
    cheats = CheatAttempt.objects.filter(session__exam=exam)

    sessions_data = []
    for session in sessions:
        student = session.student
        student_name = student.get_full_name() or student.username if student else 'نامشخص'
        student_code = student.student_code if student else '---'
        student_cheats = CheatAttempt.objects.filter(session=session)

        sessions_data.append({
            'student_name': student_name,
            'student_code': student_code,
            'cheat_count': student_cheats.count(),
            'cheats': student_cheats,
            'ip_address': session.ip_address or 'نامشخص',
            'is_active': session.is_active,
        })

    return render(request, 'teacher_panel/exam_cheats_report.html', {
        'exam': exam,
        'sessions_data': sessions_data,
        'recent_cheats': [
            {
                'student_name': c.session.student.get_full_name() or c.session.student.username if c.session and c.session.student else 'نامشخص',
                'cheat_type': c.cheat_type,
                'cheat_type_display': c.get_cheat_type_display(),
                'detail': c.detail or 'جزئیات ثبت نشده',
                'created_at': c.created_at,
            }
            for c in cheats.select_related('session__student').order_by('-created_at')[:20]
        ],
        'total_cheats': cheats.count(),
        'tab_switch_count': cheats.filter(cheat_type='tab_switch').count(),
        'copy_paste_count': cheats.filter(cheat_type='copy_paste').count(),
        'multiple_tabs_count': cheats.filter(cheat_type='multiple_tabs').count(),
        'total_students_with_cheat': len({c.session.student_id for c in cheats if c.session}),
        'total_students': sessions.count(),
    })


# ========== چاپ ==========
@login_required
def print_exam_paper(request, exam_id):
    """چاپ برگه امتحان"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    return render(request, 'teacher_panel/print_exam_paper.html', {
        'exam': exam,
        'questions': exam.questions.all().order_by('order'),
    })


@login_required
def print_answer_sheet(request, exam_id):
    """چاپ پاسخنامه"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    students_data = []
    for student in exam.students.filter(grade=exam.grade):
        answers = []
        for question in exam.questions.all().order_by('order'):
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            answers.append({
                'question': question,
                'answer': answer,
                'score': answer.score_obtained if answer else None,
            })
        students_data.append({'student': student, 'answers': answers})

    return render(request, 'teacher_panel/print_answer_sheet.html', {
        'exam': exam,
        'students_data': students_data,
    })


# ========== API ==========
def get_students_api(request):
    """API لیست دانش‌آموزان"""
    students = User.objects.filter(role='student').select_related('grade')
    return JsonResponse({
        'students': [
            {
                'id': s.id,
                'full_name': s.get_full_name() or s.username,
                'student_code': s.student_code,
                'grade_id': s.grade.id if s.grade else None,
                'grade_name': s.grade.get_name_display() if s.grade else 'نامشخص',
            }
            for s in students
        ]
    })


# teacher_panel/views.py - اضافه کردن این ویوها

from .import_export import QuestionExcelImporter, QuestionExcelExporter
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os


@login_required
def bulk_upload_questions(request, exam_id):
    """صفحه آپلود انبوه سوالات از اکسل"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')

        if not excel_file:
            return JsonResponse({'error': 'فایلی انتخاب نشده است'}, status=400)

        # بررسی پسوند فایل
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({'error': 'فرمت فایل باید Excel (.xlsx یا .xls) باشد'}, status=400)

        # بررسی حجم فایل (حداکثر 5 مگابایت)
        if excel_file.size > 5 * 1024 * 1024:
            return JsonResponse({'error': 'حجم فایل نباید بیشتر از 5 مگابایت باشد'}, status=400)

        importer = QuestionExcelImporter(exam)
        result = importer.process_file(excel_file)

        if result['success']:
            response_data = {
                'success': True,
                'success_count': result['success_count'],
                'skip_count': result['skip_count'],
                'message': f'{result["success_count"]} سوال با موفقیت اضافه شد',
            }
            if result['errors']:
                response_data['errors'] = result['errors']
            if result['warnings']:
                response_data['warnings'] = result['warnings']
            return JsonResponse(response_data)
        else:
            return JsonResponse({'error': result.get('error', 'خطا در پردازش فایل')}, status=400)

    return render(request, 'teacher_panel/bulk_upload.html', {
        'exam': exam,
    })


@login_required
def download_question_template(request):
    """دانلود فایل اکسل نمونه برای سوالات"""
    check_teacher_access(request.user)

    exporter = QuestionExcelExporter()
    template_path = exporter.create_template()

    try:
        with open(template_path, 'rb') as f:
            response = HttpResponse(
                f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = 'attachment; filename="question_template.xlsx"'
    finally:
        # حذف فایل موقت
        if os.path.exists(template_path):
            os.remove(template_path)

    return response
