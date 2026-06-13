# teacher_panel/views.py - ایمپورت‌های کامل

# ایمپورت‌های پایه Django
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q
from django.template.loader import get_template
from django.core.files.storage import default_storage

# ایمپورت‌های مدل‌ها
from exams.models import Exam, Question, StudentAnswer, ExamAttempt, ExamSession, CheatAttempt, ExamLog, TeacherAnswer
from accounts.models import User, Grade

# ایمپورت‌های کتابخانه‌های جانبی
import json
import os
import uuid
import tempfile
from datetime import datetime, timedelta
import jdatetime

# ایمپورت برای PDF
from django.http import HttpResponse
from django.template.loader import get_template
from bs4 import BeautifulSoup as HTML  # 注意: این import اشتباه است، باید اصلاح شود


# ========== توابع کمکی ==========
def to_jalali(date_val):
    """تبدیل تاریخ میلادی به شمسی"""
    if not date_val:
        return ''
    try:
        if isinstance(date_val, str):
            # اگر رشته بود، به datetime تبدیل کن
            from datetime import datetime
            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        if timezone.is_naive(date_val):
            date_val = timezone.make_aware(date_val)
        jd = jdatetime.datetime.fromgregorian(datetime=date_val)
        # نمایش کامل: سال/ماه/روز ساعت:دقیقه
        return jd.strftime('%Y/%m/%d %H:%M')
    except Exception as e:
        print(f"Jalali conversion error: {e}")
        return ''


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
    active_count = 0
    ongoing_count = 0
    inactive_count = 0

    for exam in exams:
        if not exam.is_active:
            status = 'inactive'
            status_text = 'غیرفعال'
            status_badge_class = 'status-inactive'
            status_class = 'inactive'
            inactive_count += 1
        elif exam.start_time <= now <= exam.end_time:
            status = 'ongoing'
            status_text = 'در حال برگزاری'
            status_badge_class = 'status-ongoing'
            status_class = 'ongoing'
            ongoing_count += 1
            active_count += 1
        elif exam.end_time < now:
            status = 'ended'
            status_text = 'تمام شده'
            status_badge_class = 'status-ended'
            status_class = ''
            active_count += 1
        else:
            status = 'active'
            status_text = 'فعال'
            status_badge_class = 'status-active'
            status_class = 'active'
            active_count += 1

        exam.status = status
        exam.status_text = status_text
        exam.status_badge_class = status_badge_class
        exam.status_class = status_class
        exams_with_status.append(exam)

    grades = Grade.objects.all()
    total_students = User.objects.filter(role='student').count()

    return render(request, 'teacher_panel/dashboard.html', {
        'exams': exams_with_status,
        'grades': grades,
        'active_exams_count': active_count,
        'ongoing_exams_count': ongoing_count,
        'inactive_exams_count': inactive_count,
        'total_students': total_students,
    })


# teacher_panel/views.py - اصلاح تابع create_exam

# teacher_panel/views.py - ویوهای کامل create_exam و edit_exam_info

@login_required
def create_exam(request):
    """ساخت آزمون جدید"""
    if request.user.role != 'teacher':
        return redirect('/')

    if request.method == 'POST':
        exam = Exam.objects.create(
            title=request.POST['title'],
            teacher=request.user,
            grade_id=request.POST['grade'],
            duration_minutes=int(request.POST['duration']),
            start_time=request.POST['start_time'],
            end_time=request.POST['end_time'],
            show_score_to_student='show_score' in request.POST,
            # تنظیمات امنیتی
            enable_anti_cheat='enable_anti_cheat' in request.POST,
            prevent_tab_switch='prevent_tab_switch' in request.POST,
            prevent_copy_paste='prevent_copy_paste' in request.POST,
            track_ip='track_ip' in request.POST,
            # تنظیمات نمایش سوالات
            show_questions_mode=request.POST.get('show_questions_mode', 'one_by_one'),
            show_back_button='show_back_button' in request.POST,
            # تنظیمات پاسخ تشریحی
            allow_teacher_answer='allow_teacher_answer' in request.POST,
            # ✅ نوع تایمر
            timer_type=request.POST.get('timer_type', 'floating'),
        )
        student_ids = request.POST.getlist('students')
        exam.students.set(student_ids)
        return redirect('edit_exam', exam_id=exam.id)

    grades = Grade.objects.all()
    students = User.objects.filter(role='student')

    now = timezone.now()
    default_start = now.strftime('%Y-%m-%dT%H:%M')
    default_end = (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')

    # تبدیل زمان‌های پیشنهادی به شمسی برای نمایش
    start_jalali = to_jalali(now) if now else ''
    end_jalali = to_jalali(now + timedelta(hours=2)) if now else ''

    return render(request, 'teacher_panel/create_exam.html', {
        'grades': grades,
        'students': students,
        'default_start': default_start,
        'default_end': default_end,
        'start_jalali': start_jalali,
        'end_jalali': end_jalali,
    })


@login_required
def edit_exam_info(request, exam_id):
    """مدیریت کامل آزمون - اطلاعات، تنظیمات، دانش‌آموزان و تخلفات"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    grades = Grade.objects.all()
    all_students = User.objects.filter(role='student')

    selected_student_ids = list(exam.students.values_list('id', flat=True))
    success_msg = None

    # تبدیل تاریخ به فرمت مناسب (با مدیریت خطا)
    def format_datetime_for_input(dt):
        if not dt:
            return ''
        try:
            if isinstance(dt, str):
                from datetime import datetime
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%dT%H:%M')
        except:
            return ''

    # فرمت میلادی برای input
    start_miladi = format_datetime_for_input(exam.start_time)
    end_miladi = format_datetime_for_input(exam.end_time)
    start_jalali = to_jalali(exam.start_time)
    end_jalali = to_jalali(exam.end_time)

    # دریافت اطلاعات تخلفات
    from exams.models import ExamSession, CheatAttempt
    sessions = ExamSession.objects.filter(exam=exam)
    cheats = CheatAttempt.objects.filter(session__exam=exam)

    cheats_stats = {
        'total_cheats': cheats.count(),
        'tab_switch': cheats.filter(cheat_type='tab_switch').count(),
        'copy_paste': cheats.filter(cheat_type='copy_paste').count(),
        'multiple_tabs': cheats.filter(cheat_type='multiple_tabs').count(),
    }

    recent_cheats = []
    for cheat in cheats.select_related('session__student').order_by('-created_at')[:10]:
        recent_cheats.append({
            'student_name': cheat.session.student.get_full_name() or cheat.session.student.username,
            'cheat_type_display': cheat.get_cheat_type_display(),
            'detail': cheat.detail,
            'created_at': cheat.created_at,
        })

    if request.method == 'POST':
        if 'save_info' in request.POST:
            exam.title = request.POST.get('title')
            exam.grade_id = request.POST.get('grade')
            exam.duration_minutes = int(request.POST.get('duration'))
            exam.start_time = request.POST.get('start_time')
            exam.end_time = request.POST.get('end_time')
            exam.show_score_to_student = 'show_score' in request.POST
            exam.is_active = 'is_active' in request.POST
            exam.save()
            success_msg = 'اطلاعات آزمون با موفقیت ذخیره شد'

            # بروزرسانی مجدد
            start_miladi = format_datetime_for_input(exam.start_time)
            end_miladi = format_datetime_for_input(exam.end_time)
            start_jalali = to_jalali(exam.start_time)
            end_jalali = to_jalali(exam.end_time)

        elif 'save_settings' in request.POST:
            # تنظیمات نمایش سوالات
            exam.random_questions = 'random_questions' in request.POST
            exam.show_questions_mode = request.POST.get('show_questions_mode', 'one_by_one')
            exam.show_back_button = 'show_back_button' in request.POST

            # تنظیمات امنیتی
            exam.enable_anti_cheat = 'enable_anti_cheat' in request.POST
            exam.prevent_tab_switch = 'prevent_tab_switch' in request.POST
            exam.prevent_copy_paste = 'prevent_copy_paste' in request.POST
            exam.track_ip = 'track_ip' in request.POST

            # تنظیمات پاسخ تشریحی
            exam.allow_teacher_answer = 'allow_teacher_answer' in request.POST
            exam.show_answers_after_exam = 'show_answers_after_exam' in request.POST

            # ✅ نوع تایمر - مهم
            exam.timer_type = request.POST.get('timer_type', 'floating')

            exam.save()
            success_msg = 'تنظیمات آزمون با موفقیت ذخیره شد'

        elif 'save_students' in request.POST:
            student_ids = json.loads(request.POST.get('student_ids', '[]'))
            exam.students.set(student_ids)
            selected_student_ids = student_ids
            success_msg = f'لیست دانش‌آموزان با موفقیت ذخیره شد ({len(student_ids)} نفر)'

    return render(request, 'teacher_panel/edit_exam_info.html', {
        'exam': exam,
        'grades': grades,
        'all_students': all_students,
        'students': exam.students.all(),
        'selected_student_ids': json.dumps(selected_student_ids),
        'success_msg': success_msg,
        'start_jalali': start_jalali,
        'end_jalali': end_jalali,
        'start_miladi': start_miladi,
        'end_miladi': end_miladi,
        'cheats_stats': cheats_stats,
        'recent_cheats': recent_cheats,
    })

@login_required
def edit_exam(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    questions = exam.questions.all().order_by('order')

    # دریافت اطلاعات چیت‌ها و سشن‌ها
    from exams.models import ExamSession, CheatAttempt, TeacherAnswer

    sessions = ExamSession.objects.filter(exam=exam)
    cheats = CheatAttempt.objects.filter(session__exam=exam)

    cheats_stats = {
        'total_cheats': cheats.count(),
        'tab_switch': cheats.filter(cheat_type='tab_switch').count(),
        'copy_paste': cheats.filter(cheat_type='copy_paste').count(),
        'multiple_tabs': cheats.filter(cheat_type='multiple_tabs').count(),
    }

    # آخرین تخلفات
    recent_cheats = []
    for cheat in cheats.select_related('session__student').order_by('-created_at')[:10]:
        recent_cheats.append({
            'student_name': cheat.session.student.get_full_name() or cheat.session.student.username,
            'cheat_type_display': cheat.get_cheat_type_display(),
            'detail': cheat.detail,
            'created_at': cheat.created_at,
        })

    # سوالاتی که پاسخ تشریحی معلم دارند
    questions_with_teacher_answer = []
    for q in questions:
        teacher_answer = TeacherAnswer.objects.filter(question=q).first()
        if teacher_answer and teacher_answer.answer_text:
            questions_with_teacher_answer.append({
                'question': q,
                'answer_text': teacher_answer.answer_text,
                'answer_image': teacher_answer.answer_image,
            })

    return render(request, 'teacher_panel/edit_exam.html', {
        'exam': exam,
        'questions': questions,
        'cheats_stats': cheats_stats,
        'recent_cheats': recent_cheats,
        'questions_with_teacher_answer': questions_with_teacher_answer,
    })




@login_required
def add_question(request, exam_id):
    """افزودن سوال جدید"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)

    if request.method == 'POST':
        question = Question.objects.create(
            exam=exam,
            text=request.POST.get('text', ''),
            question_type=request.POST['question_type'],
            max_score=float(request.POST['max_score']),
            order=exam.questions.count() + 1,
            allow_image_answer='allow_image_answer' in request.POST,
        )

        if 'image' in request.FILES:
            question.image = request.FILES['image']

        q_type = request.POST['question_type']

        if q_type == 'multiple_choice':
            options = []
            for i in range(1, 5):
                opt = request.POST.get(f'option_{i}', '')
                options.append(opt if opt else f"گزینه {i}")
            question.options = options
            question.options_type = request.POST.get('options_type', 'text')
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'true_false':
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'fill_blank':
            blanks = request.POST.get('blanks', '').split(',')
            question.blanks = [b.strip() for b in blanks if b.strip()]
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'short_answer':
            question.correct_answer = request.POST.get('correct_answer')

        elif q_type == 'long_answer':
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


# teacher_panel/views.py - اضافه کردن این ویوها

from exams.models import ExamSession, CheatAttempt, TeacherAnswer, ExamLog


@login_required
def exam_cheats_report(request, exam_id):
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)

    from exams.models import ExamSession, CheatAttempt
    from accounts.models import User

    # همه جلسات فعال این آزمون
    sessions = ExamSession.objects.filter(exam=exam).select_related('student')

    print("=" * 50)
    print(f"تعداد جلسات: {sessions.count()}")
    for s in sessions:
        print(f"Session ID: {s.id}, Student ID: {s.student_id}, Student: {s.student}")
        if s.student:
            print(f"  - Username: {s.student.username}")
            print(f"  - Full name: {s.student.get_full_name()}")
    print("=" * 50)

    # آمار کلی
    cheats = CheatAttempt.objects.filter(session__exam=exam)
    total_cheats = cheats.count()
    tab_switch_count = cheats.filter(cheat_type='tab_switch').count()
    copy_paste_count = cheats.filter(cheat_type='copy_paste').count()
    multiple_tabs_count = cheats.filter(cheat_type='multiple_tabs').count()

    # داده‌های دانش‌آموزان
    sessions_data = []
    students_with_cheat = set()

    for session in sessions:
        # دریافت پاسخ صحیح نام دانش‌آموز
        if session.student:
            student_name = session.student.get_full_name()
            if not student_name:
                student_name = session.student.username
            student_code = session.student.student_code or '---'
        else:
            student_name = 'نامشخص'
            student_code = '---'

        student_cheats = CheatAttempt.objects.filter(session=session)
        cheat_count = student_cheats.count()

        sessions_data.append({
            'student_name': student_name,
            'student_code': student_code,
            'cheat_count': cheat_count,
            'cheats': student_cheats,
            'ip_address': session.ip_address or 'نامشخص',
            'is_active': session.is_active,
        })

        if cheat_count > 0:
            students_with_cheat.add(session.student.id if session.student else 0)

    # آخرین تخلفات
    recent_cheats = []
    for cheat in cheats.select_related('session__student').order_by('-created_at')[:20]:
        if cheat.session and cheat.session.student:
            student_name = cheat.session.student.get_full_name()
            if not student_name:
                student_name = cheat.session.student.username
        else:
            student_name = 'نامشخص'

        recent_cheats.append({
            'student_name': student_name,
            'cheat_type': cheat.cheat_type,
            'cheat_type_display': cheat.get_cheat_type_display(),
            'detail': cheat.detail or 'جزئیات ثبت نشده',
            'created_at': cheat.created_at,
        })

    return render(request, 'teacher_panel/exam_cheats_report.html', {
        'exam': exam,
        'sessions_data': sessions_data,
        'recent_cheats': recent_cheats,
        'total_cheats': total_cheats,
        'tab_switch_count': tab_switch_count,
        'copy_paste_count': copy_paste_count,
        'multiple_tabs_count': multiple_tabs_count,
        'total_students_with_cheat': len(students_with_cheat),
        'total_students': sessions.count(),
    })


@login_required
def view_student_answers(request, exam_id):
    """مشاهده پاسخ‌های دانش‌آموزان با قابلیت نمره‌دهی"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)

    # دانش‌آموزانی که آزمون را انجام داده‌اند
    attempts = ExamAttempt.objects.filter(exam=exam, status='submitted').select_related('student')
    questions = exam.questions.all().order_by('order')

    students_data = []
    for attempt in attempts:
        student = attempt.student
        answers_data = []
        total_score = 0
        total_possible = 0

        for question in questions:
            student_answer = StudentAnswer.objects.filter(student=student, question=question).first()
            score = student_answer.score_obtained if student_answer and student_answer.score_obtained else 0
            total_score += score
            total_possible += question.max_score

            # پاسخ تشریحی معلم
            teacher_answer = TeacherAnswer.objects.filter(question=question).first()

            answers_data.append({
                'question': question,
                'answer': student_answer,
                'score': score,
                'max_score': question.max_score,
                'teacher_answer': teacher_answer,
                'is_correct': score == question.max_score if score else False,
            })

        percentage = (total_score / total_possible * 100) if total_possible > 0 else 0

        students_data.append({
            'student': student,
            'attempt': attempt,
            'answers': answers_data,
            'total_score': total_score,
            'total_possible': total_possible,
            'percentage': round(percentage, 1),
        })

    # مرتب‌سازی بر اساس نمره
    students_data.sort(key=lambda x: x['total_score'], reverse=True)

    return render(request, 'teacher_panel/view_student_answers.html', {
        'exam': exam,
        'students_data': students_data,
        'questions': questions,
    })


@login_required
def save_student_score(request, exam_id, student_id, question_id):
    """ذخیره نمره برای یک سوال خاص (AJAX)"""
    if request.method == 'POST':
        data = json.loads(request.body)
        score = float(data.get('score', 0))

        answer = StudentAnswer.objects.filter(
            student_id=student_id,
            question_id=question_id,
            question__exam_id=exam_id,
            question__exam__teacher=request.user
        ).first()

        if answer:
            answer.score_obtained = score
            answer.graded_by = request.user
            answer.graded_at = timezone.now()
            answer.save()
            return JsonResponse({'success': True, 'score': score})

        return JsonResponse({'success': False, 'error': 'پاسخ یافت نشد'})

    return JsonResponse({'success': False, 'error': 'روش غیرمجاز'})


@login_required
def add_teacher_answer(request, exam_id, question_id):
    """افزودن/ویرایش پاسخ تشریحی معلم"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    question = get_object_or_404(Question, id=question_id, exam=exam)

    if request.method == 'POST':
        teacher_answer, created = TeacherAnswer.objects.get_or_create(question=question)
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

    teacher_answer = TeacherAnswer.objects.filter(question=question).first()

    return render(request, 'teacher_panel/add_teacher_answer.html', {
        'exam': exam,
        'question': question,
        'teacher_answer': teacher_answer,
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


@login_required
def edit_question(request, exam_id, question_id):
    """ویرایش سوال"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    question = get_object_or_404(Question, id=question_id, exam=exam)

    if request.method == 'POST':
        question.text = request.POST.get('text', '')
        question.question_type = request.POST.get('question_type')
        question.max_score = float(request.POST.get('max_score'))
        question.allow_image_answer = 'allow_image_answer' in request.POST

        if 'remove_image' in request.POST and question.image:
            question.image.delete(save=False)
            question.image = None

        if 'image' in request.FILES:
            question.image = request.FILES['image']

        q_type = request.POST['question_type']
        correct_val = request.POST.get('correct_answer', '')

        if q_type == 'multiple_choice':
            options = []
            for i in range(1, 5):
                opt = request.POST.get(f'option_{i}', '')
                options.append(opt if opt else f"گزینه {i}")
            question.options = options
            question.options_type = request.POST.get('options_type', 'text')
            question.correct_answer = correct_val

        elif q_type == 'true_false':
            question.correct_answer = correct_val

        elif q_type == 'fill_blank':
            blanks = request.POST.get('blanks', '').split(',')
            question.blanks = [b.strip() for b in blanks if b.strip()]
            question.correct_answer = correct_val

        elif q_type == 'short_answer':
            question.correct_answer = correct_val

        elif q_type == 'long_answer':
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


@login_required
def grade_exam(request, exam_id):
    """صفحه تصحیح دستی آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    questions = exam.questions.all().order_by('order')
    students = exam.students.filter(grade=exam.grade)
    grades = Grade.objects.all()

    questions_with_answers = []
    for question in questions:
        answers_list = []
        for student in students:
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            if not answer:
                answer = StudentAnswer.objects.create(
                    student=student,
                    question=question,
                    answer_text=''
                )

            is_correct = False
            if answer.answer_text and question.correct_answer:
                if question.question_type in ['true_false', 'multiple_choice']:
                    is_correct = (answer.answer_text.strip().lower() == question.correct_answer.strip().lower())
                elif question.question_type == 'fill_blank':
                    is_correct = (answer.answer_text.strip().lower() == question.correct_answer.strip().lower())

            answers_list.append({
                'student': student,
                'answer_text': answer.answer_text if answer.answer_text else None,
                'answer_image': answer.answer_image if answer.answer_image else None,
                'answer_id': answer.id,
                'score': answer.score_obtained,
                'is_correct': is_correct,
                'correct_answer': question.correct_answer,
            })

        questions_with_answers.append({
            'id': question.id,
            'text': question.text,
            'question_type': question.question_type,
            'max_score': question.max_score,
            'answers_data': answers_list,
            'correct_answer': question.correct_answer,
        })

    return render(request, 'teacher_panel/grade_exam.html', {
        'exam': exam,
        'questions': questions_with_answers,
        'students': students,
        'grades': grades,
    })


@login_required
def save_score(request):
    """ذخیره نمره برای یک پاسخ (AJAX)"""
    if request.method == 'POST':
        answer_id = request.POST.get('answer_id')
        score = float(request.POST.get('score'))

        answer = get_object_or_404(StudentAnswer, id=answer_id)
        answer.score_obtained = score
        answer.graded_by = request.user
        answer.graded_at = timezone.now()
        answer.save()

        return JsonResponse({'success': True})
    return JsonResponse({'success': False})


@login_required
def exam_results(request, exam_id):
    """نمایش نتایج نهایی آزمون بعد از تصحیح"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    students = exam.students.filter(grade=exam.grade)

    results = []
    for student in students:
        total_score = 0
        total_possible = 0
        answered_questions = 0

        for question in exam.questions.all():
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            total_possible += question.max_score

            if answer and answer.score_obtained is not None:
                total_score += answer.score_obtained
                answered_questions += 1

        percentage = (total_score / total_possible * 100) if total_possible > 0 else 0

        results.append({
            'student': student,
            'total_score': total_score,
            'total_possible': total_possible,
            'percentage': round(percentage, 1),
            'answered_count': answered_questions,
            'total_questions': exam.questions.count(),
        })

    results.sort(key=lambda x: x['total_score'], reverse=True)

    stats = {
        'average_score': round(sum(r['total_score'] for r in results) / len(results), 2) if results else 0,
        'highest_score': round(max(r['total_score'] for r in results), 2) if results else 0,
        'lowest_score': round(min(r['total_score'] for r in results), 2) if results else 0,
        'total_students': len(results),
        'fully_graded': sum(1 for r in results if r['answered_count'] == r['total_questions']),
    }

    return render(request, 'teacher_panel/exam_results.html', {
        'exam': exam,
        'results': results,
        'stats': stats,
    })


# ========== ویوهای مدیریتی جدید ==========


# ========== ویوهای API و کمکی ==========

def get_students_api(request):
    """API برای گرفتن لیست دانش‌آموزان با فرمت JSON"""
    students = User.objects.filter(role='student').select_related('grade')
    data = {
        'students': [
            {
                'id': s.id,
                'full_name': s.get_full_name() or s.username,
                'student_code': s.student_code,
                'grade_id': s.grade.id if s.grade else None,
                'grade_name': s.grade.get_name_display() if s.grade else 'نامشخص'
            }
            for s in students
        ]
    }
    return JsonResponse(data)


@login_required
def toggle_exam_status(request, exam_id):
    """فعال/غیرفعال کردن آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    exam.is_active = not exam.is_active
    exam.save()
    return redirect('teacher_dashboard')


# teacher_panel/views.py

@login_required
def delete_exam(request, exam_id):
    """حذف آزمون"""
    if request.user.role != 'teacher':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    exam.delete()

    # اگه درخواست AJAX هست
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    # اگه درخواست معمولی هست
    messages.success(request, 'آزمون با موفقیت حذف شد')
    return redirect('teacher_dashboard')
# ========== ویوهای چاپ ==========

@login_required
def print_exam_paper(request, exam_id):
    """چاپ برگه امتحان"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    questions = exam.questions.all().order_by('order')
    return render(request, 'teacher_panel/print_exam_paper.html', {
        'exam': exam,
        'questions': questions,
    })


@login_required
def print_answer_sheet(request, exam_id):
    """چاپ پاسخنامه دانش‌آموزان"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    students = exam.students.filter(grade=exam.grade)

    students_data = []
    for student in students:
        answers = []
        for question in exam.questions.all().order_by('order'):
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            answers.append({
                'question': question,
                'answer': answer,
                'score': answer.score_obtained if answer else None,
            })
        students_data.append({
            'student': student,
            'answers': answers,
        })

    return render(request, 'teacher_panel/print_answer_sheet.html', {
        'exam': exam,
        'students_data': students_data,
    })

# @login_required
# def download_pdf(request, exam_id, paper_type):
#     """دانلود PDF برگه امتحان یا پاسخنامه"""
#     exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
#
#     if paper_type == 'exam':
#         questions = exam.questions.all().order_by('order')
#         template = get_template('teacher_panel/print_exam_paper.html')
#         context = {'exam': exam, 'questions': questions}
#         filename = f"برگه_امتحان_{exam.title}.pdf"
#     else:
#         students = exam.students.filter(grade=exam.grade)
#         students_data = []
#         for student in students:
#             answers = []
#             for question in exam.questions.all().order_by('order'):
#                 answer = StudentAnswer.objects.filter(student=student, question=question).first()
#                 answers.append({
#                     'question': question,
#                     'answer': answer,
#                     'score': answer.score_obtained if answer else None,
#                 })
#             students_data.append({
#                 'student': student,
#                 'answers': answers,
#             })
#         template = get_template('teacher_panel/print_answer_sheet.html')
#         context = {'exam': exam, 'students_data': students_data}
#         filename = f"پاسخنامه_{exam.title}.pdf"
#
#     html_string = template.render(context, request)
#
#     # ایجاد PDF با xhtml2pdf
#     from io import BytesIO
#     result = BytesIO()
#     pdf = pisa.pisaDocument(BytesIO(html_string.encode('UTF-8')), result)
#
#     if not pdf.err:
#         response = HttpResponse(result.getvalue(), content_type='application/pdf')
#         response['Content-Disposition'] = f'attachment; filename="{filename}"'
#         return response
#
#     return HttpResponse('خطا در تولید PDF', status=500)
