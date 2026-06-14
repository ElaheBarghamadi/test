# student_panel/views.py
# -*- coding: utf-8 -*-

import os
import random
import uuid
import json
import hmac
import hashlib
from decimal import Decimal
from functools import wraps

import jdatetime
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.conf import settings
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from django.core.files.images import get_image_dimensions

from exams.models import Exam, Question, StudentAnswer, ExamAttempt, ExamSession, CheatAttempt
from accounts.models import Grade

# ========== تنظیمات هش امنیتی ==========
SECRET_KEY_FOR_HASH = getattr(settings, 'EXAM_ID_HASH_SECRET', settings.SECRET_KEY)


def hash_exam_id(exam_id):
    """هش کردن ID آزمون برای استفاده در URL"""
    if not exam_id:
        return ''
    hashed = hmac.new(
        SECRET_KEY_FOR_HASH.encode('utf-8'),
        str(exam_id).encode('utf-8'),
        hashlib.sha256
    ).hexdigest()[:16]
    return f"{exam_id}_{hashed}"


def decode_exam_id(hashed_id):
    """استخراج ID واقعی از هش"""
    try:
        parts = hashed_id.split('_')
        if len(parts) != 2:
            return None
        exam_id, hash_str = parts
        exam_id = int(exam_id)

        expected_hash = hmac.new(
            SECRET_KEY_FOR_HASH.encode('utf-8'),
            str(exam_id).encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:16]

        if hmac.compare_digest(hash_str, expected_hash):
            return exam_id
        return None
    except (ValueError, TypeError):
        return None


def exam_access_required(view_func):
    """دکوریتور بررسی دسترسی با هش"""

    @wraps(view_func)
    def wrapper(request, hashed_exam_id, *args, **kwargs):
        exam_id = decode_exam_id(hashed_exam_id)
        if not exam_id:
            raise Http404('لینک آزمون معتبر نیست')

        exam = get_object_or_404(Exam, id=exam_id)

        if request.user.role != 'student':
            raise PermissionDenied('شما دسترسی دانش‌آموز ندارید')

        if request.user not in exam.students.all():
            raise PermissionDenied('شما به این آزمون دسترسی ندارید')

        if request.user.grade != exam.grade:
            raise PermissionDenied('پایه تحصیلی شما با این آزمون همخوانی ندارد')

        return view_func(request, exam, *args, **kwargs)

    return wrapper


# ========== توابع کمکی ==========
def to_jalali(date_val):
    """تبدیل تاریخ میلادی به شمسی"""
    if not date_val:
        return ''
    try:
        if timezone.is_naive(date_val):
            date_val = timezone.make_aware(date_val)
        jd = jdatetime.datetime.fromgregorian(datetime=date_val)
        return jd.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def get_exam_semester(exam):
    """تشخیص نیمسال بر اساس تاریخ آزمون"""
    if not exam.start_time:
        return 'general'
    month = exam.start_time.month
    if 7 <= month <= 11:
        return 'first'
    elif 12 <= month <= 3:
        return 'second'
    return 'final'


def get_current_semester():
    """دریافت نیمسال جاری"""
    now = timezone.now()
    month = now.month
    if 7 <= month <= 11:
        return 'اول'
    elif 12 <= month <= 3:
        return 'دوم'
    return 'تابستان'


def validate_image_file(file_obj, max_size=5 * 1024 * 1024):
    """اعتبارسنجی فایل تصویر"""
    if not file_obj:
        return False, 'فایلی ارسال نشده است'

    if file_obj.size > max_size:
        return False, 'حجم فایل نباید بیشتر از 5 مگابایت باشد'

    try:
        width, height = get_image_dimensions(file_obj)
        if width is None or height is None:
            return False, 'فرمت فایل نامعتبر است'
    except:
        return False, 'فرمت فایل پشتیبانی نمی‌شود'

    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    ext = os.path.splitext(file_obj.name)[1].lower()
    if ext not in allowed_extensions:
        return False, 'فرمت مجاز: JPEG, PNG, GIF, WEBP'

    return True, 'OK'


@login_required
def student_dashboard(request):
    """داشبورد دانش‌آموز با کارنامه کامل"""
    if request.user.role != 'student':
        return redirect('/')

    now = timezone.now()
    student = request.user

    exams = Exam.objects.filter(students=student).order_by('-created_at')

    exams_with_status = []
    for exam in exams:
        attempt = ExamAttempt.objects.filter(student=student, exam=exam).first()

        if not exam.is_active:
            status = 'inactive'
            status_text = 'غیرفعال'
            status_badge_class = 'status-inactive'
            status_class = 'inactive'
            can_start = False
        elif exam.start_time <= now <= exam.end_time:
            status = 'ongoing'
            status_text = 'در حال برگزاری'
            status_badge_class = 'status-ongoing'
            status_class = 'ongoing'
            can_start = True
        elif exam.end_time < now:
            status = 'ended'
            status_text = 'تمام شده'
            status_badge_class = 'status-ended'
            status_class = 'ended'
            can_start = False
        elif exam.start_time > now:
            status = 'not_started'
            status_text = 'شروع نشده'
            status_badge_class = 'status-not-started'
            status_class = 'not-started'
            can_start = False
        else:
            status = 'active'
            status_text = 'فعال'
            status_badge_class = 'status-active'
            status_class = 'active'
            can_start = True

        exams_with_status.append({
            'exam': exam,
            'attempt': attempt,
            'hashed_id': hash_exam_id(exam.id),
            'status': status,
            'status_text': status_text,
            'status_badge_class': status_badge_class,
            'status_class': status_class,
            'can_start': can_start,
            'start_time_jalali': to_jalali(exam.start_time),
            'end_time_jalali': to_jalali(exam.end_time),
        })

    # نتایج ثبت شده
    completed_attempts = ExamAttempt.objects.filter(
        student=student,
        status='submitted'
    ).select_related('exam')

    completed_results = []
    total_score_sum = Decimal('0.00')
    total_possible_sum = Decimal('0.00')

    for attempt in completed_attempts:
        answers = StudentAnswer.objects.filter(
            student=student,
            question__exam=attempt.exam
        )

        total_score = Decimal('0.00')
        total_possible = Decimal('0.00')

        for a in answers:
            # ✅ تبدیل امن به Decimal
            if a.score_obtained is not None:
                try:
                    total_score += Decimal(str(a.score_obtained))
                except:
                    total_score += Decimal('0.00')
            if a.question.max_score is not None:
                try:
                    total_possible += Decimal(str(a.question.max_score))
                except:
                    total_possible += Decimal('0.00')

        total_score_float = float(total_score)
        total_possible_float = float(total_possible)
        percentage = (total_score_float / total_possible_float * 100) if total_possible_float > 0 else 0
        show_score = attempt.exam.show_score_to_student

        completed_results.append({
            'exam': attempt.exam,
            'attempt': attempt,
            'score': total_score_float,
            'total_possible': total_possible_float,
            'percentage': round(percentage, 1),
            'date_jalali': to_jalali(attempt.submitted_at or attempt.updated_at),
            'show_score': show_score,
        })

        if show_score:
            total_score_sum += total_score
            total_possible_sum += total_possible

    # محاسبه معدل
    total_score_sum_float = float(total_score_sum)
    total_possible_sum_float = float(total_possible_sum)
    overall_average = (total_score_sum_float / total_possible_sum_float * 20) if total_possible_sum_float > 0 else 0

    # کارنامه
    try:
        from admin_panel.models import SystemSetting
        show_report_card = SystemSetting.get_setting('show_report_card_to_students', False)
    except ImportError:
        show_report_card = getattr(settings, 'SHOW_REPORT_CARD', False)

    report_data = []
    for result in completed_results:
        if result['show_score']:
            report_data.append({
                'exam_title': result['exam'].title,
                'score': result['score'],
                'total_possible': result['total_possible'],
                'percentage': result['percentage'],
                'date_jalali': result['date_jalali'],
                'semester': get_exam_semester(result['exam']),
                'grade_name': result['exam'].grade.get_name_display() if result['exam'].grade else '',
            })

    return render(request, 'student_panel/dashboard.html', {
        'exams_with_status': exams_with_status,
        'completed_results': completed_results,
        'now': now,
        'overall_average': round(overall_average, 2),
        'total_possible_sum': float(total_possible_sum),
        'show_report_card': show_report_card,
        'report_data': report_data,
        'current_semester': get_current_semester(),
    })

@login_required
@exam_access_required
def take_exam(request, exam):
    """صفحه شرکت در آزمون - با هش امنیتی"""
    # گرفتن یا ایجاد تلاش
    attempt, created = ExamAttempt.objects.get_or_create(
        student=request.user,
        exam=exam,
        defaults={'status': 'in_progress', 'started_at': timezone.now()}
    )

    if attempt.status == 'submitted':
        return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))

    if not exam.is_active:
        return render(request, 'student_panel/exam_inactive.html', {'exam': exam})

    now = timezone.now()
    remaining = 0

    # محاسبه زمان باقی‌مانده
    if exam.timer_type == 'fixed':
        if now > exam.end_time:
            attempt.status = 'submitted'
            attempt.submitted_at = now
            attempt.save()
            return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))
        remaining = (exam.end_time - now).total_seconds()
    else:
        if attempt.started_at:
            elapsed = (now - attempt.started_at).total_seconds()
            remaining = max(0, (exam.duration_minutes * 60) - elapsed)
        else:
            attempt.started_at = now
            attempt.save()
            remaining = exam.duration_minutes * 60

        if remaining <= 0:
            attempt.status = 'submitted'
            attempt.submitted_at = now
            attempt.save()
            return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))

    # گرفتن سوالات
    questions = list(exam.questions.all())
    if exam.random_questions:
        random.Random(request.user.id + exam.id).shuffle(questions)

    # تنظیم گزینه‌های پیش‌فرض
    for q in questions:
        if q.question_type == 'multiple_choice' and not q.options:
            q.options = ['گزینه 1', 'گزینه 2', 'گزینه 3', 'گزینه 4']

    # گرفتن پاسخ‌های قبلی
    saved_answers = {}
    for answer in StudentAnswer.objects.filter(student=request.user, question__exam=exam):
        saved_answers[answer.question_id] = {
            'answer_text': answer.answer_text,
            'answer_image': answer.answer_image.url if answer.answer_image else None,
        }

    # ✅ محاسبه hashed_exam_id
    hashed_exam_id = hash_exam_id(exam.id)

    return render(request, 'student_panel/take_exam.html', {
        'exam': exam,
        'questions': questions,
        'remaining_seconds': int(remaining),
        'saved_answers': json.dumps(saved_answers),
        'duration_minutes': exam.duration_minutes,
        'timer_type': exam.timer_type,
        'end_time_jalali': to_jalali(exam.end_time) if exam.timer_type == 'fixed' else None,
        'hashed_exam_id': hashed_exam_id,  # ✅ اضافه شده
    })
# ========== ذخیره پاسخ ==========
@require_http_methods(["POST"])
@login_required
def save_answer(request):
    """ذخیره پاسخ دانش‌آموز (AJAX)"""
    try:
        data = json.loads(request.body)
        question_id = data.get('question_id')
        answer_text = data.get('answer_text', '').strip()

        if len(answer_text) > 10000:
            return JsonResponse({'error': 'پاسخ بیش از حد طولانی است'}, status=400)

        question = get_object_or_404(Question, id=question_id)

        if request.user not in question.exam.students.all():
            return JsonResponse({'error': 'شما مجاز به پاسخ دادن نیستید'}, status=403)

        attempt = ExamAttempt.objects.filter(student=request.user, exam=question.exam).first()
        if attempt and attempt.status in ['submitted', 'timeout']:
            return JsonResponse({'error': 'زمان آزمون به اتمام رسیده'}, status=403)

        answer, created = StudentAnswer.objects.update_or_create(
            student=request.user,
            question=question,
            defaults={'answer_text': answer_text}
        )

        return JsonResponse({'success': True, 'saved_at': str(answer.updated_at)})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'داده نامعتبر'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def save_answer_image(request):
    """ذخیره عکس به عنوان پاسخ دانش‌آموز"""
    try:
        question_id = request.POST.get('question_id')
        answer_image = request.FILES.get('answer_image')

        is_valid, error_msg = validate_image_file(answer_image)
        if not is_valid:
            return JsonResponse({'error': error_msg}, status=400)

        question = get_object_or_404(Question, id=question_id)

        if not question.allow_image_answer and question.question_type != 'image_answer':
            return JsonResponse({'error': 'این سوال اجازه آپلود عکس ندارد'}, status=403)

        if request.user not in question.exam.students.all():
            return JsonResponse({'error': 'شما مجاز به پاسخ دادن نیستید'}, status=403)

        attempt = ExamAttempt.objects.filter(student=request.user, exam=question.exam).first()
        if attempt and attempt.status in ['submitted', 'timeout']:
            return JsonResponse({'error': 'زمان آزمون به اتمام رسیده'}, status=403)

        ext = os.path.splitext(answer_image.name)[1].lower()
        safe_filename = f"answer_{request.user.id}_{uuid.uuid4().hex}{ext}"

        answer, created = StudentAnswer.objects.update_or_create(
            student=request.user,
            question=question,
            defaults={'answer_image': answer_image}
        )

        if answer.answer_image:
            old_path = answer.answer_image.path
            new_path = os.path.join(os.path.dirname(old_path), safe_filename)
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
            answer.answer_image.name = f"student_answers/{safe_filename}"
            answer.save()

        return JsonResponse({
            'success': True,
            'image_url': answer.answer_image.url if answer.answer_image else None
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def remove_answer_image(request):
    """حذف عکس پاسخ دانش‌آموز"""
    try:
        data = json.loads(request.body)
        question_id = data.get('question_id')

        answer = StudentAnswer.objects.filter(student=request.user, question_id=question_id).first()
        if answer and answer.answer_image:
            answer.answer_image.delete(save=False)
            answer.answer_image = None
            answer.save()
            return JsonResponse({'success': True})

        return JsonResponse({'success': False})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ========== ثبت نهایی ==========
@login_required
@exam_access_required
def submit_exam(request, exam):
    """ثبت نهایی آزمون"""
    attempt = get_object_or_404(ExamAttempt, student=request.user, exam=exam)

    if attempt.status == 'submitted':
        return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))

    attempt.status = 'submitted'
    attempt.submitted_at = timezone.now()
    attempt.save()

    return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))


@login_required
@exam_access_required
def exam_thanks(request, exam):
    """صفحه تشکر بعد از ثبت آزمون"""
    return render(request, 'student_panel/thanks.html', {'exam': exam})

@login_required
def exam_result_detail(request, exam_id):
    """نمایش جزئیات نتیجه یک آزمون برای دانش‌آموز"""
    exam = get_object_or_404(Exam, id=exam_id)

    if request.user not in exam.students.all():
        return redirect('student_dashboard')

    if not exam.show_score_to_student:
        return redirect('student_dashboard')

    attempt = ExamAttempt.objects.filter(student=request.user, exam=exam, status='submitted').first()
    if not attempt:
        return redirect('student_dashboard')

    total_score = Decimal('0.00')
    total_possible = Decimal('0.00')
    question_scores = []

    for question in exam.questions.all().order_by('order'):
        answer = StudentAnswer.objects.filter(student=request.user, question=question).first()

        # تبدیل به Decimal برای محاسبات یکسان
        max_score = Decimal(str(question.max_score)) if question.max_score else Decimal('0.00')
        total_possible += max_score

        if answer and answer.score_obtained is not None:
            # تبدیل score_obtained به Decimal
            score = Decimal(str(answer.score_obtained)) if answer.score_obtained else Decimal('0.00')
        else:
            score = Decimal('0.00')

        total_score += score

        question_scores.append({
            'question': question,
            'answer': answer,
            'score': float(score),  # برای نمایش در قالب به float تبدیل می‌شود
            'max_score': float(max_score),
        })

    total_score_float = float(total_score)
    total_possible_float = float(total_possible)
    percentage = (total_score_float / total_possible_float * 100) if total_possible_float > 0 else 0

    return render(request, 'student_panel/exam_result_detail.html', {
        'exam': exam,
        'total_score': total_score_float,
        'total_possible': total_possible_float,
        'percentage': round(percentage, 1),
        'question_scores': question_scores,
    })
# ========== API ==========
@login_required
@exam_access_required
def check_exam_time(request, exam):
    """چک کردن زمان باقی‌مانده آزمون (AJAX)"""
    attempt = ExamAttempt.objects.filter(student=request.user, exam=exam).first()
    now = timezone.now()

    if exam.timer_type == 'fixed':
        remaining = max(0, (exam.end_time - now).total_seconds()) if now <= exam.end_time else 0
    else:
        if attempt and attempt.started_at:
            elapsed = (now - attempt.started_at).total_seconds()
            remaining = max(0, (exam.duration_minutes * 60) - elapsed)
        else:
            remaining = exam.duration_minutes * 60

    return JsonResponse({'remaining_seconds': int(remaining)})


@login_required
def log_cheat(request):
    """ثبت تخلف دانش‌آموز (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'})

    try:
        data = json.loads(request.body)
        exam_id = data.get('exam_id')
        cheat_type = data.get('cheat_type')
        detail = data.get('detail', '')[:500]

        valid_cheat_types = ['tab_switch', 'copy_paste', 'right_click', 'multiple_tabs', 'inactivity']
        if cheat_type not in valid_cheat_types:
            return JsonResponse({'success': False, 'error': 'نوع تخلف نامعتبر'})

        exam = get_object_or_404(Exam, id=exam_id)

        if request.user not in exam.students.all():
            return JsonResponse({'success': False, 'error': 'شما به این آزمون دسترسی ندارید'})

        session, _ = ExamSession.objects.get_or_create(
            student=request.user,
            exam=exam,
            defaults={
                'ip_address': request.META.get('REMOTE_ADDR', '')[:45],
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200]
            }
        )

        CheatAttempt.objects.create(
            session=session,
            cheat_type=cheat_type,
            detail=detail
        )

        return JsonResponse({'success': True})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'داده نامعتبر'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})