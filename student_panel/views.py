# student_panel/views.py
# -*- coding: utf-8 -*-

import os
import random
import uuid
import json
import hmac
import hashlib
from datetime import timedelta
from decimal import Decimal
from functools import wraps

import jdatetime
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from django.core.files.images import get_image_dimensions

from exams.models import (Exam, Question, StudentAnswer, ExamAttempt, ExamSession,
                          CheatAttempt, TeacherAnswer)
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
    """تبدیل تاریخ میلادی به شمسی (بر اساس منطقه زمانی تهران)"""
    if not date_val:
        return ''
    try:
        if timezone.is_naive(date_val):
            date_val = timezone.make_aware(date_val)
        else:
            # ⚠️ بدون این تبدیل، ساعت UTC نمایش داده می‌شد (۳:۳۰ اختلاف با تهران)
            date_val = timezone.localtime(date_val)
        jd = jdatetime.datetime.fromgregorian(datetime=date_val)
        return jd.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def get_exam_semester(exam):
    """تشخیص نیمسال بر اساس تاریخ آزمون"""
    if not exam.start_time:
        return 'general'
    month = exam.start_time.month
    if 7 <= month <= 11:          # مهر تا آبان/آذر
        return 'first'
    elif month == 12 or month <= 3:   # اسفند تا فروردین/خرداد
        return 'second'
    return 'final'


def get_current_semester():
    """دریافت نیمسال جاری"""
    now = timezone.localtime(timezone.now())
    month = now.month
    if 7 <= month <= 11:
        return 'اول'
    elif month == 12 or month <= 3:
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


# ========== توابع کمکی آزمون (تنظیمات معلم) ==========
SUBMIT_GRACE_SECONDS = 120  # فرصت ذخیره پاسخ‌ها لحظاتی بعد از پایان تایمر


def get_client_ip(request):
    """استخراج IP واقعی کاربر (با پشتیبانی از پروکسی)"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        ip = forwarded.split(',')[0].strip()
        if ip:
            return ip[:45]
    return (request.META.get('REMOTE_ADDR', '') or '')[:45]


def exam_deadline(exam, attempt):
    """محاسبه مهلت پایان آزمون بر اساس نوع تایمر انتخابی معلم"""
    if exam.timer_type == 'fixed':
        return exam.end_time
    if attempt and attempt.started_at:
        return attempt.started_at + timedelta(minutes=exam.duration_minutes or 0)
    return None


def exam_window_open(exam, attempt, grace_seconds=SUBMIT_GRACE_SECONDS):
    """آیا هنوز امکان ذخیره پاسخ وجود دارد؟ (با اندکی فرصت برای ثبت خودکار)"""
    deadline = exam_deadline(exam, attempt)
    if not deadline:
        return True
    if timezone.is_naive(deadline):
        deadline = timezone.make_aware(deadline)
    return timezone.now() <= deadline + timedelta(seconds=grace_seconds)


def render_correct_answer(question):
    """پاسخ صحیح به شکل خوانا (برای نمایش بعد از آزمون، فقط اگر معلم اجازه داده باشد)"""
    correct = (question.correct_answer or '').strip()
    if not correct:
        return ''

    qtype = question.question_type
    if qtype == 'true_false':
        return '✅ صحیح' if correct.lower() == 'true' else '❌ غلط'

    if qtype == 'multiple_choice':
        options = question.options or []
        try:
            idx = int(correct) - 1
        except (TypeError, ValueError):
            return correct
        if 0 <= idx < len(options):
            return f'گزینه {idx + 1}: {options[idx]}'
        return correct

    if qtype == 'fill_blank':
        parts = [p.strip() for p in correct.replace('،', ',').split(',') if p.strip()]
        blanks = question.blanks or []
        if len(parts) > 1:
            lines = []
            for i, val in enumerate(parts):
                label = str(blanks[i]).strip() if i < len(blanks) and blanks[i] else f'جای خالی {i + 1}'
                lines.append(f'{label}: {val}')
            return '\n'.join(lines)
        return correct

    if qtype == 'matching':
        try:
            selections = json.loads(correct)
        except (TypeError, ValueError):
            return correct
        pairs = question.matching_pairs or []
        lines = []
        for i, pair in enumerate(pairs):
            key = f'pair_{question.id}_{i}'
            value = selections.get(key)
            left = pair.get('left', '')
            right = ''
            if value:
                try:
                    idx = int(str(value).split('_')[-1])
                    if 0 <= idx < len(pairs):
                        right = pairs[idx].get('right', '')
                except (TypeError, ValueError):
                    right = ''
            lines.append(f'{left} ← {right or "—"}')
        return '\n'.join(lines)

    return correct


def track_exam_session(request, exam):
    """ثبت/به‌روزرسانی نشست آزمون در صورت فعال بودن «ردیابی IP» توسط معلم"""
    if not exam.track_ip:
        return None

    ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:200]

    session, created = ExamSession.objects.get_or_create(
        student=request.user,
        exam=exam,
        defaults={
            'ip_address': ip or None,
            'user_agent': user_agent,
            'is_active': True,
        },
    )

    if created:
        return session

    previous_ip = session.ip_address
    changed = False

    if ip and ip != previous_ip:
        if exam.enable_anti_cheat:
            CheatAttempt.objects.create(
                session=session,
                cheat_type='different_ip',
                detail=f'ورود با IP جدید: {ip} (IP قبلی: {previous_ip or "نامشخص"})',
            )
        session.ip_address = ip
        changed = True

    if user_agent and user_agent != session.user_agent:
        session.user_agent = user_agent
        changed = True

    if not session.is_active:
        session.is_active = True
        changed = True

    if changed:
        session.save()
    else:
        ExamSession.objects.filter(pk=session.pk).update(last_activity=timezone.now())

    return session


def _normalize_fa(value):
    """یکسان‌سازی متن فارسی برای مقایسه (ی/ك عربی، نیم‌فاصله، فاصله اضافی)"""
    if value is None:
        return ''
    text = str(value).strip().lower()
    text = text.replace('\u200c', ' ').replace('\u064a', 'ی').replace('\u0643', 'ک').replace('\u0629', 'ه')
    return ' '.join(text.split())


def blank_labels(blanks, correct_answer):
    """برچسب جاهای خالی برای نمایش به دانش‌آموز

    اگر معلم به‌جای «عنوان» جاهای خالی، خودِ پاسخ‌ها را در این فیلد وارد کرده باشد،
    برای جلوگیری از لو رفتن پاسخ، برچسب‌ها خالی فرستاده می‌شوند (فقط تعداد محفوظ می‌ماند).
    """
    items = [str(b).strip() for b in (blanks or [])]
    if not items:
        return []
    correct_parts = str(correct_answer or '').replace('،', ',').split(',')
    correct_set = {_normalize_fa(p) for p in correct_parts if p.strip()}
    if any(_normalize_fa(b) and _normalize_fa(b) in correct_set for b in items):
        return ['' for _ in items]
    return items


def build_fill_blank_text(values):
    """ساخت متن پاسخ جاخالی از فهرست ورودی‌ها: «مقدار۱ | مقدار۲»"""
    if not isinstance(values, (list, tuple)):
        return None
    cleaned = [('' if v is None else str(v)).strip() for v in values]
    if not any(cleaned):
        return ''
    return ' | '.join(cleaned)



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
            'date_jalali': to_jalali(attempt.submitted_at or attempt.started_at or attempt.exam.end_time),
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
    now = timezone.now()

    # ⚠️ اول تلاشِ موجود را می‌خوانیم؛ چون get_or_create با started_at=now
    # ساخته می‌شد و عملاً همیشه «آزمون شروع شده» به حساب می‌آمد.
    attempt = ExamAttempt.objects.filter(student=request.user, exam=exam).first()

    if attempt and attempt.status == 'submitted':
        return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))

    if not exam.is_active:
        return render(request, 'student_panel/exam_inactive.html', {
            'exam': exam,
            'reason': 'inactive',
            'start_time_jalali': to_jalali(exam.start_time),
            'end_time_jalali': to_jalali(exam.end_time),
        })

    # ⚠️ قبل از زمان شروع، امکان ورود به آزمون وجود ندارد
    if exam.start_time and now < exam.start_time:
        return render(request, 'student_panel/exam_inactive.html', {
            'exam': exam,
            'reason': 'not_started',
            'start_time_jalali': to_jalali(exam.start_time),
            'end_time_jalali': to_jalali(exam.end_time),
        })

    # ⚠️ بعد از پایان آزمون، فقط کسی که قبلاً شروع کرده می‌تواند ادامه دهد
    if exam.end_time and now > exam.end_time and not (attempt and attempt.started_at):
        return render(request, 'student_panel/exam_inactive.html', {
            'exam': exam,
            'reason': 'ended',
            'start_time_jalali': to_jalali(exam.start_time),
            'end_time_jalali': to_jalali(exam.end_time),
        })

    # گرفتن یا ایجاد تلاش
    attempt, created = ExamAttempt.objects.get_or_create(
        student=request.user,
        exam=exam,
        defaults={'status': 'in_progress', 'started_at': now}
    )

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
    questions = list(exam.questions.all().order_by('order', 'id'))
    if exam.random_questions:
        random.Random(request.user.id + exam.id).shuffle(questions)

    # تنظیم گزینه‌های پیش‌فرض و داده‌های موردنیاز قالب
    total_score = 0.0
    for q in questions:
        if q.question_type == 'multiple_choice' and not q.options:
            q.options = ['گزینه 1', 'گزینه 2', 'گزینه 3', 'گزینه 4']

        # ⚠️ خروجی list پایتون (repr) جاوااسکریپت معتبر نیست؛ اگر متن گزینه
        # شامل ' یا </script> باشد صفحه می‌شکند. برای همین JSON سریال می‌کنیم.
        q.options_json = json.dumps(q.options or [], ensure_ascii=False)
        q.matching_pairs_json = json.dumps(q.matching_pairs or [], ensure_ascii=False)
        blanks_list = list(q.blanks or [])
        q.blanks_json = json.dumps(blank_labels(blanks_list, q.correct_answer), ensure_ascii=False)
        q.blanks_count = len(blanks_list) or 1

        # ✅ داده‌های مشتق‌شده برای قالب/جاوااسکریپت
        q.options_type = q.options_type or 'text'
        q.can_upload = bool(q.allow_image_answer or q.question_type == 'image_answer')
        q.type_display = q.get_question_type_display()
        try:
            total_score += float(q.max_score or 0)
        except (TypeError, ValueError):
            pass

    # ✅ ردیابی IP طبق تنظیمات معلم
    track_exam_session(request, exam)

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
        'saved_answers': json.dumps(saved_answers, ensure_ascii=False),
        'saved_answers_data': saved_answers,
        'duration_minutes': exam.duration_minutes,
        'timer_type': exam.timer_type,
        'start_time_jalali': to_jalali(exam.start_time),
        'end_time_jalali': to_jalali(exam.end_time),
        'total_score': ('%g' % total_score),
        'attempt_started_jalali': to_jalali(attempt.started_at) if attempt.started_at else '',
        'hashed_exam_id': hashed_exam_id,  # ✅ اضافه شده
    })
# ========== ذخیره پاسخ ==========
def _resolve_question(question_id):
    return Question.objects.filter(id=question_id).first() if question_id else None


def answer_guard(user, question):
    """بررسی‌های مشترک مجوز پاسخ‌دهی

    برگشت: شیء ExamAttempt (یا None) در حالت مجاز، وگرنه JsonResponse خطا.
    - آزمون ثبت‌نهایی‌شده باشد → ۴۰۳
    - آزمون هنوز شروع نشده باشد → ۴۰۳ (جلوگیری از پاسخ دادن پیش از شروع)
    - تایمر شناور بدون نشست شروع‌شده → ۴۰۳
    - مهلت آزمون تمام شده باشد → ۴۰۳
    """
    exam = question.exam
    attempt = ExamAttempt.objects.filter(student=user, exam=exam).first()

    if attempt and attempt.status in ['submitted', 'timeout']:
        return JsonResponse({'error': 'آزمون ثبت نهایی شده است'}, status=403)

    now = timezone.now()
    if exam.start_time and now < exam.start_time:
        return JsonResponse({'error': 'آزمون هنوز شروع نشده است'}, status=403)

    if exam.timer_type == 'floating' and (not attempt or not attempt.started_at):
        return JsonResponse({'error': 'آزمون هنوز شروع نشده است'}, status=403)

    if not exam_window_open(exam, attempt):
        return JsonResponse({'error': 'زمان آزمون به پایان رسیده است'}, status=403)

    return attempt


def _apply_answer_payload(user, question, data):
    """اعمال یک پاسخ روی StudentAnswer — پاسخ ۴۰۰/۴۰۳ یا شیء ذخیره‌شده"""
    guard = answer_guard(user, question)
    if isinstance(guard, JsonResponse):
        return guard

    raw_text = data.get('answer_text', None)
    blanks = data.get('blanks', None)

    # ✅ سوال جاخالی: چند ورودی مستقل → یک متن واحد «مقدار۱ | مقدار۲»
    if question.question_type == 'fill_blank' and blanks is not None:
        raw_text = build_fill_blank_text(blanks)
        if raw_text is None:
            return JsonResponse({'error': 'مقادیر جای خالی نامعتبر است'}, status=400)

    if raw_text is not None and not isinstance(raw_text, str):
        return JsonResponse({'error': 'پاسخ نامعتبر است'}, status=400)

    answer_text = None if raw_text is None else raw_text.strip()
    if answer_text is not None and len(answer_text) > 10000:
        return JsonResponse({'error': 'پاسخ بیش از حد طولانی است'}, status=400)

    defaults = {}
    # ⚠️ answer_text=None یعنی «بدون تغییر» (مثلاً فقط عکس آپلود شده است)
    if answer_text is not None:
        defaults['answer_text'] = answer_text

    if not defaults:
        answer = StudentAnswer.objects.filter(student=user, question=question).first()
        if not answer:
            answer = StudentAnswer.objects.create(student=user, question=question, answer_text='')
        return answer

    answer, _created = StudentAnswer.objects.update_or_create(
        student=user,
        question=question,
        defaults=defaults,
    )
    return answer


@require_http_methods(["POST"])
@login_required
def save_answer(request):
    """ذخیره پاسخ دانش‌آموز (AJAX)"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'داده نامعتبر'}, status=400)

    try:
        question = _resolve_question(data.get('question_id'))

        # ⚠️ به‌جای get_object_or_404؛ چون Http404 داخل except Exception
        # به پاسخ 500 تبدیل می‌شد و خطای نامعتبر به‌صورت خطای سرور نمایش داده می‌شد
        if not question:
            return JsonResponse({'error': 'سوال یافت نشد'}, status=404)

        if request.user not in question.exam.students.all():
            return JsonResponse({'error': 'شما مجاز به پاسخ دادن نیستید'}, status=403)

        answer = _apply_answer_payload(request.user, question, data)
        if isinstance(answer, JsonResponse):
            return answer

        return JsonResponse({'success': True, 'saved_at': str(answer.updated_at)})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def save_all_answers(request):
    """ذخیره دسته‌ای همه پاسخ‌ها در یک درخواست (برای ثبت نهایی مطمئن)"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'داده نامعتبر'}, status=400)

    try:
        exam_id = data.get('exam_id')
        answers = data.get('answers') or {}

        exam = Exam.objects.filter(id=exam_id).first() if exam_id else None
        if not exam:
            return JsonResponse({'error': 'آزمون یافت نشد'}, status=404)

        if request.user not in exam.students.all():
            return JsonResponse({'error': 'شما مجاز به پاسخ دادن نیستید'}, status=403)

        attempt = ExamAttempt.objects.filter(student=request.user, exam=exam).first()
        if attempt and attempt.status in ['submitted', 'timeout']:
            return JsonResponse({'success': True, 'saved': 0, 'skipped': len(answers),
                                 'warning': 'آزمون قبلاً ثبت نهایی شده است'})

        if not exam_window_open(exam, attempt):
            return JsonResponse({'error': 'زمان آزمون به پایان رسیده است'}, status=403)

        if not isinstance(answers, dict):
            return JsonResponse({'error': 'داده نامعتبر'}, status=400)

        saved = 0
        failed = 0
        question_ids = []
        for key in list(answers.keys())[:200]:
            try:
                question_ids.append(int(key))
            except (TypeError, ValueError):
                failed += 1

        questions = {q.id: q for q in Question.objects.filter(id__in=question_ids, exam=exam)}

        for qid, value in answers.items():
            question = questions.get(int(qid)) if str(qid).isdigit() else None
            if not question:
                failed += 1
                continue

            payload = value if isinstance(value, dict) else {'answer_text': value}
            result = _apply_answer_payload(request.user, question, payload)
            if isinstance(result, JsonResponse):
                failed += 1
            else:
                saved += 1

        return JsonResponse({'success': True, 'saved': saved, 'failed': failed})

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

        question = Question.objects.filter(id=question_id).first() if question_id else None
        if not question:
            return JsonResponse({'error': 'سوال یافت نشد'}, status=404)

        if not question.allow_image_answer and question.question_type != 'image_answer':
            return JsonResponse({'error': 'این سوال اجازه آپلود عکس ندارد'}, status=403)

        if request.user not in question.exam.students.all():
            return JsonResponse({'error': 'شما مجاز به پاسخ دادن نیستید'}, status=403)

        guard = answer_guard(request.user, question)
        if isinstance(guard, JsonResponse):
            return guard

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
            guard = answer_guard(request.user, answer.question)
            if isinstance(guard, JsonResponse):
                return guard

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
    """ثبت نهایی آزمون (GET: ریدایرکت / POST: ذخیره پاسخ‌ها + ثبت نهایی)"""
    # ✅ در حالت POST می‌توان پاسخ‌های نهایی را همراه درخواست فرستاد
    if request.method == 'POST':
        try:
            data = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            data = {}

        answers = data.get('answers') if isinstance(data, dict) else None
        if isinstance(answers, dict) and answers:
            attempt_check = ExamAttempt.objects.filter(student=request.user, exam=exam).first()
            already_done = bool(attempt_check and attempt_check.status in ['submitted', 'timeout'])
            if not already_done:
                question_ids = [int(k) for k in answers.keys() if str(k).isdigit()]
                questions = {q.id: q for q in Question.objects.filter(id__in=question_ids, exam=exam)}
                for qid, value in answers.items():
                    question = questions.get(int(qid)) if str(qid).isdigit() else None
                    if not question:
                        continue
                    payload = value if isinstance(value, dict) else {'answer_text': value}
                    result = _apply_answer_payload(request.user, question, payload)
                    if isinstance(result, JsonResponse) and result.status_code == 403:
                        break

    attempt = get_object_or_404(ExamAttempt, student=request.user, exam=exam)

    if attempt.status == 'submitted':
        if request.method == 'POST':
            return JsonResponse({'success': True, 'already_submitted': True,
                                 'redirect': reverse('exam_thanks', kwargs={'hashed_exam_id': hash_exam_id(exam.id)})})
        return redirect('exam_thanks', hashed_exam_id=hash_exam_id(exam.id))

    attempt.status = 'submitted'
    attempt.submitted_at = timezone.now()
    attempt.save()

    # ✅ تصحیح خودکار پاسخ‌های عینی (تستی/صحیح‌غلط/جاخالی/وصل‌کردنی)
    from exams.grading import auto_grade_attempt
    auto_grade_attempt(request.user, exam)

    # بستن نشست ردیابی IP
    if exam.track_ip:
        ExamSession.objects.filter(student=request.user, exam=exam).update(is_active=False)

    if request.method == 'POST':
        return JsonResponse({'success': True,
                             'redirect': reverse('exam_thanks', kwargs={'hashed_exam_id': hash_exam_id(exam.id)})})

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

    show_score = bool(exam.show_score_to_student)
    show_answers = bool(exam.show_answers_after_exam)

    # ⚠️ اگر معلم هیچ‌کدام را فعال نکرده باشد، دانش‌آموز کارنامه‌ای نمی‌بیند
    if not show_score and not show_answers:
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

        item = {
            'question': question,
            'answer': answer,
            'score': float(score),  # برای نمایش در قالب به float تبدیل می‌شود
            'max_score': float(max_score),
            'correct_display': '',
            'teacher_answer': None,
        }
        if show_answers:
            item['correct_display'] = render_correct_answer(question)
            item['teacher_answer'] = TeacherAnswer.objects.filter(question=question).first()
        question_scores.append(item)

    total_score_float = float(total_score)
    total_possible_float = float(total_possible)
    percentage = (total_score_float / total_possible_float * 100) if total_possible_float > 0 else 0

    return render(request, 'student_panel/exam_result_detail.html', {
        'exam': exam,
        'total_score': total_score_float,
        'total_possible': total_possible_float,
        'percentage': round(percentage, 1),
        'question_scores': question_scores,
        'show_score': show_score,
        'show_answers': show_answers,
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
        detail = str(data.get('detail') or '')[:500]

        # همه انواع تخلف تعریف‌شده در مدل (قبلاً screenshot/print_screen رد می‌شدند)
        valid_cheat_types = [c[0] for c in CheatAttempt.CHEAT_TYPES]
        if cheat_type not in valid_cheat_types:
            return JsonResponse({'success': False, 'error': 'نوع تخلف نامعتبر'})

        exam = Exam.objects.filter(id=exam_id).first() if exam_id else None
        if not exam:
            return JsonResponse({'success': False, 'error': 'آزمون یافت نشد'}, status=404)

        if request.user not in exam.students.all():
            return JsonResponse({'success': False, 'error': 'شما به این آزمون دسترسی ندارید'})

        # ⚠️ محدودیت نرخ ثبت تخلف (جلوگیری از اسپم/DoS روی جدول تخلف‌ها)
        throttle_key = f'cheat-throttle:{request.user.id}:{exam.id}'
        count = cache.get(throttle_key, 0)
        if count >= 120:
            return JsonResponse({'success': False, 'error': 'تعداد درخواست زیاد'})
        cache.add(throttle_key, 0, 3600)
        try:
            cache.incr(throttle_key)
        except ValueError:
            pass

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