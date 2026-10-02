# panel_admin/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from django.core.paginator import Paginator
from django.contrib import messages
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings

from accounts.models import User, Grade
from exams.models import (Exam, Question, StudentAnswer, ExamAttempt, CheatAttempt,
                          ExamLog, ExamSession)
from .models import SystemSetting, SecurityEvent, record_security_event, parse_user_agent
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import pandas as pd
import openpyxl
from io import BytesIO, StringIO
import csv


def to_decimal(value, default=Decimal('0')):
    """تبدیل امن هر مقدار (float/str/Decimal/None) به Decimal"""
    if value is None or value == '':
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def clean_numeric_text(value):
    """
    پاکسازی مقادیر خوانده‌شده از اکسل.
    pandas اعداد را به float تبدیل می‌کند، برای همین کد دانش‌آموزی یا رمز عبور
    عددی به شکل «140312001.0» خوانده می‌شد. این تابع آن را به «140312001» تبدیل می‌کند.
    """
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.lower() in ('nan', 'none', 'nat'):
        return ''
    # عددی که به شکل رشته با .0 ذخیره شده
    if text.endswith('.0') and text[:-2].isdigit():
        text = text[:-2]
    return text


@login_required
def admin_dashboard(request):
    """داشبورد اصلی ادمین - آمار کامل"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    now = timezone.now()

    # آمار کلی
    stats = {
        'total_students': User.objects.filter(role='student').count(),
        'total_teachers': User.objects.filter(role='teacher').count(),
        'total_admins': User.objects.filter(role='admin').count(),
        'total_all': User.objects.count(),
        'total_exams': Exam.objects.count(),
        'total_questions': Question.objects.count(),
        'active_exams': Exam.objects.filter(is_active=True).count(),
        'total_attempts': ExamAttempt.objects.count(),
        'submitted_attempts': ExamAttempt.objects.filter(status='submitted').count(),
        'total_answers': StudentAnswer.objects.count(),
        'graded_answers': StudentAnswer.objects.filter(score_obtained__isnull=False).count(),
    }

    # آمار پایه‌ها
    grade_stats = []
    for grade in Grade.objects.all():
        students = User.objects.filter(role='student', grade=grade).count()
        exams = Exam.objects.filter(grade=grade).count()
        attempts = ExamAttempt.objects.filter(exam__grade=grade, status='submitted').count()

        # ⚠️ همه مقادیر باید Decimal باشند: max_score از نوع Decimal و
        # score_obtained از نوع Float است و جمع/تقسیم این دو با هم TypeError می‌دهد.
        total_score = Decimal('0')
        total_possible = Decimal('0')
        for attempt in ExamAttempt.objects.filter(exam__grade=grade, status='submitted'):
            for question in attempt.exam.questions.all():
                answer = StudentAnswer.objects.filter(student=attempt.student, question=question).first()
                total_possible += to_decimal(question.max_score)
                if answer and answer.score_obtained:
                    total_score += to_decimal(answer.score_obtained)

        avg_score = float(total_score / total_possible * 100) if total_possible > 0 else 0

        grade_stats.append({
            'grade': grade,
            'students': students,
            'exams': exams,
            'attempts': attempts,
            'avg_score': round(avg_score, 1),
        })

    # آخرین آزمون‌ها
    recent_exams = Exam.objects.all().order_by('-created_at')[:10]
    exams_data = []
    for exam in recent_exams:
        exams_data.append({
            'exam': exam,
            'attempts': ExamAttempt.objects.filter(exam=exam).count(),
            'submitted': ExamAttempt.objects.filter(exam=exam, status='submitted').count(),
        })

    # آخرین کاربران
    recent_users = User.objects.all().order_by('-date_joined')[:10]

    # فعالیت‌های اخیر
    recent_activities = []
    for attempt in ExamAttempt.objects.filter(status='submitted').order_by('-submitted_at')[:5]:
        recent_activities.append({
            'type': 'exam_submit',
            'message': f'دانش‌آموز {attempt.student.get_full_name()} آزمون {attempt.exam.title} را ثبت کرد',
            'time': attempt.submitted_at,
        })

    monthly_stats = []
    for i in range(6):
        month_date = now - timedelta(days=30 * i)
        month_start = month_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if i == 0:
            month_end = now
        else:
            next_month = month_start + timedelta(days=32)
            month_end = next_month.replace(day=1) - timedelta(days=1)

        exams_count = Exam.objects.filter(created_at__range=[month_start, month_end]).count()
        attempts_count = ExamAttempt.objects.filter(submitted_at__range=[month_start, month_end]).count()

        try:
            import jdatetime
            _FA_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
            month_label = _FA_MONTHS[jdatetime.datetime.fromgregorian(datetime=month_start).month - 1]
        except Exception:
            month_label = month_start.strftime('%B')
        monthly_stats.append({
            'month': month_label,
            'exams': exams_count,
            'attempts': attempts_count,
        })

    context = {
        'stats': stats,
        'grade_stats': grade_stats,
        'exams_data': exams_data,
        'recent_users': recent_users,
        'recent_activities': recent_activities,
        'monthly_stats': monthly_stats,
    }

    return render(request, 'admin_panel/dashboard.html', context)


@login_required
def manage_users(request):
    """مدیریت کاربران"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    users = User.objects.all().order_by('-date_joined')
    grades = Grade.objects.all()

    # فیلتر و جستجو
    q = request.GET.get('q', '').strip()
    role_f = request.GET.get('role', '').strip()
    grade_f = request.GET.get('grade', '').strip()
    if q:
        users = users.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(username__icontains=q) | Q(student_code__icontains=q)
        )
    if role_f in ('student', 'teacher', 'admin'):
        users = users.filter(role=role_f)
    if grade_f.isdigit():
        users = users.filter(grade_id=int(grade_f))

    # pagination
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # دریافت آمار برای نمایش در قالب
    stats = {
        'total_students': User.objects.filter(role='student').count(),
        'total_teachers': User.objects.filter(role='teacher').count(),
        'total_admins': User.objects.filter(role='admin').count(),
        'total_all': User.objects.count(),
    }

    return render(request, 'admin_panel/manage_users.html', {
        'users': page_obj,
        'grades': grades,
        'stats': stats,
        'q': q,
        'role_f': role_f,
        'grade_f': grade_f,
    })


@login_required
def import_users_from_file(request):
    """
    آپلود فایل اکسل یا CSV و ثبت خودکار کاربران
    فرمت فایل باید شامل ستون‌های زیر باشد:
    - first_name (نام)
    - last_name (نام خانوادگی)
    - username (نام کاربری) - الزامی
    - password (رمز عبور) - الزامی
    - role (نقش: student, teacher, admin)
    - student_code (کد دانش‌آموزی - فقط برای دانش‌آموزان)
    - grade_id (شناسه پایه - اختیاری)
    """
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        file = request.FILES.get('file')
        if not file:
            return JsonResponse({'error': 'لطفا فایل را انتخاب کنید'}, status=400)

        # بررسی پسوند فایل
        file_extension = file.name.split('.')[-1].lower()

        if file_extension in ['xlsx', 'xls']:
            # خواندن فایل اکسل
            # index_col=False → ستون اول هرگز به عنوان ایندکس در نظر گرفته نمی‌شود
            df = pd.read_excel(file, index_col=False)
        elif file_extension == 'csv':
            # خواندن فایل CSV با تشخیص خودکار انکودینگ
            # (فایل‌های ساخته‌شده در اکسل فارسی معمولاً cp1256 یا utf-8-sig هستند)
            raw = file.read()
            file_content = None
            for encoding in ('utf-8-sig', 'utf-8', 'cp1256', 'latin-1'):
                try:
                    file_content = raw.decode(encoding)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if file_content is None:
                return JsonResponse({'error': 'انکودینگ فایل قابل تشخیص نیست'}, status=400)
            df = pd.read_csv(StringIO(file_content), index_col=False)
        else:
            return JsonResponse({'error': 'فرمت فایل پشتیبانی نمی‌شود. فقط اکسل (xlsx, xls) و CSV'}, status=400)

        # ستون‌های مورد نیاز
        required_columns = ['username', 'password']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return JsonResponse({'error': f'ستون‌های زیر در فایل وجود ندارند: {", ".join(missing_columns)}'},
                                status=400)

        # آمار ثبت‌نام
        success_count = 0
        failed_count = 0
        errors = []
        created_users = []

        for index, row in df.iterrows():
            # شماره ردیف برای نمایش در پیام‌های خطا
            # (اگر فایل ستون اضافه داشته باشد، index می‌تواند رشته باشد)
            try:
                row_no = int(index) + 2
            except (TypeError, ValueError):
                row_no = str(index)

            try:
                username = clean_numeric_text(row.get('username'))
                password = clean_numeric_text(row.get('password'))
                first_name = clean_numeric_text(row.get('first_name'))
                last_name = clean_numeric_text(row.get('last_name'))
                role = clean_numeric_text(row.get('role')).lower() or 'student'
                student_code = clean_numeric_text(row.get('student_code'))
                grade_id = clean_numeric_text(row.get('grade_id')) or None

                # اعتبارسنجی
                if not username:
                    errors.append(f'ردیف {row_no}: نام کاربری خالی است')
                    failed_count += 1
                    continue

                if not password:
                    errors.append(f'ردیف {row_no}: رمز عبور خالی است')
                    failed_count += 1
                    continue

                if User.objects.filter(username=username).exists():
                    errors.append(f'ردیف {row_no}: نام کاربری {username} تکراری است')
                    failed_count += 1
                    continue

                if role not in ['student', 'teacher', 'admin']:
                    errors.append(f'ردیف {row_no}: نقش {role} نامعتبر است (فقط student, teacher, admin)')
                    failed_count += 1
                    continue

                if role == 'student' and student_code:
                    if User.objects.filter(student_code=student_code).exists():
                        errors.append(f'ردیف {row_no}: کد دانش‌آموزی {student_code} تکراری است')
                        failed_count += 1
                        continue

                # ایجاد کاربر
                user = User.objects.create(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                )
                user.set_password(password)

                # تنظیم پایه تحصیلی
                if grade_id and grade_id != 'nan' and grade_id != '':
                    try:
                        grade_id_int = int(float(grade_id))
                        grade = Grade.objects.filter(id=grade_id_int).first()
                        if grade:
                            user.grade = grade
                    except (ValueError, TypeError):
                        pass

                if role == 'student':
                    user.student_code = student_code if student_code else None

                user.save()
                success_count += 1
                created_users.append({
                    'username': username,
                    'role': role,
                    'full_name': f"{first_name} {last_name}".strip()
                })

            except Exception as e:
                errors.append(f'ردیف {row_no}: {str(e)}')
                failed_count += 1

        return JsonResponse({
            'success': True,
            'success_count': success_count,
            'failed_count': failed_count,
            'errors': errors[:20],  # حداکثر 20 خطا برگردون
            'created_users': created_users[:10],  # حداکثر 10 کاربر ایجاد شده
        })

    except Exception as e:
        return JsonResponse({'error': f'خطا در پردازش فایل: {str(e)}'}, status=500)


@login_required
def download_users_template(request):
    """دانلود فایل نمونه برای ثبت کاربران"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    import pandas as pd
    from django.http import HttpResponse

    # ایجاد دیتافریم نمونه
    sample_data = {
        'first_name': ['علی', 'محمد', 'زهرا', 'رضا'],
        'last_name': ['محمدی', 'کریمی', 'احمدی', 'رضایی'],
        'username': ['ali.mohammadi', 'mohammad.karimi', 'zahra.ahmadi', 'reza.rezaii'],
        'password': ['12345678', '12345678', '12345678', '12345678'],
        'role': ['student', 'student', 'teacher', 'admin'],
        'student_code': ['140312001', '140312002', '', ''],
        'grade_id': ['1', '2', '', ''],
    }

    df = pd.DataFrame(sample_data)

    # توضیحات ستون‌ها
    descriptions = pd.DataFrame({
        'توضیحات ستون': [
            'نام (اختیاری)',
            'نام خانوادگی (اختیاری)',
            'نام کاربری (الزامی - یکتا)',
            'رمز عبور (الزامی - حداقل 6 کاراکتر)',
            'نقش: student, teacher, admin (پیش‌فرض student)',
            'کد دانش‌آموزی (فقط برای دانش‌آموزان - اختیاری)',
            'شناسه پایه تحصیلی (اختیاری - از جدول grades)'
        ]
    })

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="users_import_template.xlsx"'

    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='users', index=False)
        descriptions.to_excel(writer, sheet_name='راهنما', index=False)

    return response


@login_required
def add_user(request):
    """افزودن کاربر جدید (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        username = request.POST.get('username')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        role = request.POST.get('role')
        grade_id = request.POST.get('grade')
        student_code = request.POST.get('student_code', '')

        if not username:
            return JsonResponse({'error': 'نام کاربری الزامی است'}, status=400)

        if not password:
            return JsonResponse({'error': 'رمز عبور الزامی است'}, status=400)

        if len(password) < 6:
            return JsonResponse({'error': 'رمز عبور باید حداقل 6 کاراکتر باشد'}, status=400)

        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': 'این نام کاربری قبلاً ثبت شده است'}, status=400)

        if role == 'student' and student_code:
            if User.objects.filter(student_code=student_code).exists():
                return JsonResponse({'error': 'این کد دانش‌آموزی قبلاً ثبت شده است'}, status=400)

        user = User.objects.create(
            username=username,
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        user.set_password(password)

        if grade_id and grade_id != 'None' and grade_id != '' and grade_id != 'null':
            try:
                user.grade_id = int(grade_id)
            except (ValueError, TypeError):
                pass

        if role == 'student':
            user.student_code = student_code if student_code else None

        user.save()

        record_security_event(request, user=request.user, event_type='account_created',
                              severity='notice',
                              detail=f'ساخت حساب «{user.username}» با نقش {user.get_role_display()}')

        return JsonResponse({'success': True, 'user_id': user.id, 'message': 'کاربر با موفقیت اضافه شد'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_user(request, user_id):
    """دریافت اطلاعات یک کاربر (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    user = get_object_or_404(User, id=user_id)
    return JsonResponse({
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'grade_id': user.grade.id if user.grade else None,
        'student_code': user.student_code,
    })


@login_required
def edit_user(request, user_id):
    """ویرایش کاربر (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        user = get_object_or_404(User, id=user_id)

        username = request.POST.get('username')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        role = request.POST.get('role')
        grade_id = request.POST.get('grade')
        password = request.POST.get('password')
        student_code = request.POST.get('student_code', '')

        if not username:
            return JsonResponse({'error': 'نام کاربری الزامی است'}, status=400)

        if User.objects.filter(username=username).exclude(id=user_id).exists():
            return JsonResponse({'error': 'این نام کاربری قبلاً ثبت شده است'}, status=400)

        if role == 'student' and student_code:
            if User.objects.filter(student_code=student_code).exclude(id=user_id).exists():
                return JsonResponse({'error': 'این کد دانش‌آموزی قبلاً ثبت شده است'}, status=400)

        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.role = role

        if grade_id and grade_id != 'None' and grade_id != '' and grade_id != 'null':
            try:
                user.grade_id = int(grade_id)
            except (ValueError, TypeError):
                user.grade = None
        else:
            user.grade = None

        if role == 'student':
            user.student_code = student_code if student_code else None
        else:
            user.student_code = None

        password_changed = False
        if password and password.strip():
            if len(password) >= 6:
                user.set_password(password)
                password_changed = True
            else:
                return JsonResponse({'error': 'رمز عبور باید حداقل 6 کاراکتر باشد'}, status=400)

        user.save()

        record_security_event(request, user=request.user,
                              event_type='password_changed' if password_changed else 'profile_updated',
                              severity='notice',
                              detail=(f'{"بازنشانی رمز عبور" if password_changed else "ویرایش مشخصات"} '
                                      f'کاربر «{user.username}» توسط مدیر'))

        return JsonResponse({'success': True, 'message': 'کاربر با موفقیت ویرایش شد'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def delete_user(request, user_id):
    """حذف کاربر (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    user = get_object_or_404(User, id=user_id)

    if user.id == request.user.id:
        return JsonResponse({'error': 'نمی‌توانید خودتان را حذف کنید'}, status=400)

    record_security_event(request, user=request.user, event_type='account_deleted',
                          severity='warning', detail=f'حذف حساب کاربری «{user.username}» (شناسه {user_id})')
    user.delete()
    return JsonResponse({'success': True, 'message': 'کاربر با موفقیت حذف شد'})


# ============================================================================
#  صفحهٔ «جزئیات کاربر» — پروفایل، نشست‌های فعال، دستگاه/آی‌پی، فعالیت، امنیت
# ============================================================================

_SESSION_STORE = None


def _session_engine():
    """موتور نشست فعلی (پیش‌فرض: django.contrib.sessions.backends.db)"""
    global _SESSION_STORE
    if _SESSION_STORE is None:
        from importlib import import_module
        from django.conf import settings as dj
        _SESSION_STORE = import_module(dj.SESSION_ENGINE).SessionStore
    return _SESSION_STORE


def _user_login_sessions(user):
    """نشست‌های ورودِ فعال کاربر (کوکی نشست) با اطلاعات دستگاه و زمان انقضا"""
    from django.contrib.sessions.models import Session
    now = timezone.now()
    rows = []
    qs = Session.objects.filter(expire_date__gt=now).order_by('-expire_date')
    for s in qs:
        try:
            data = s.get_decoded()
        except Exception:
            continue
        if str(data.get('_auth_user_id')) != str(user.id):
            continue
        rows.append({
            'session_key': s.session_key,
            'expire_date': s.expire_date,
            'expires_in': s.expire_date - now,
            'is_current': False,   # بعداً با نشست جاری مقایسه می‌شود
        })
    return rows


def _attempt_score(student, exam):
    """(نمره کسب‌شده، نمره کل، درصد) برای یک دانش‌آموز در یک آزمون"""
    total = Decimal('0')
    possible = Decimal('0')
    for q in exam.questions.all():
        possible += to_decimal(q.max_score)
    for a in StudentAnswer.objects.filter(student=student, question__exam=exam).select_related('question'):
        if a.score_obtained is not None:
            total += to_decimal(a.score_obtained)
    pct = float(total / possible * 100) if possible > 0 else 0.0
    return float(total), float(possible), round(pct, 1)


def _relative_fa(dt_value, now=None):
    """«۳ ساعت پیش» / «دیروز» — خروجی فارسی با ارقام فارسی"""
    if not dt_value:
        return '—'
    now = now or timezone.now()
    if timezone.is_naive(dt_value):
        dt_value = timezone.make_aware(dt_value)
    delta = now - dt_value
    secs = int(delta.total_seconds())
    fa = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
    if secs < 0:
        return 'در آینده'
    if secs < 60:
        return 'همین حالا'
    if secs < 3600:
        return f'{secs // 60} دقیقه پیش'.translate(fa)
    if secs < 86400:
        return f'{secs // 3600} ساعت پیش'.translate(fa)
    if secs < 172800:
        return 'دیروز'
    if secs < 86400 * 30:
        return f'{secs // 86400} روز پیش'.translate(fa)
    if secs < 86400 * 365:
        return f'{secs // (86400 * 30)} ماه پیش'.translate(fa)
    return f'{secs // (86400 * 365)} سال پیش'.translate(fa)


def _remaining_fa(dt_value, now=None):
    """زمان باقی‌مانده تا انقضای نشست: «۱۱ ساعت و ۲۰ دقیقه مانده»"""
    if not dt_value:
        return '—'
    now = now or timezone.now()
    if timezone.is_naive(dt_value):
        dt_value = timezone.make_aware(dt_value)
    secs = int((dt_value - now).total_seconds())
    fa = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
    if secs <= 0:
        return 'منقضی شده'
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f'{d} روز')
    if h:
        parts.append(f'{h} ساعت')
    if not d and m:
        parts.append(f'{m} دقیقه')
    if not parts:
        parts.append('کمتر از ۱ دقیقه')
    return (' و '.join(parts) + ' مانده').translate(fa)


@login_required
def user_detail(request, user_id):
    """جزئیات کامل یک کاربر برای مدیر: مشخصات، نشست‌ها، دستگاه/آی‌پی، فعالیت، امنیت"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    target = get_object_or_404(User.objects.select_related('grade'), id=user_id)
    now = timezone.now()

    # ---------------- نشست‌های ورود فعال ----------------
    login_sessions = _user_login_sessions(target)
    current_key = request.session.session_key
    for s in login_sessions:
        s['is_current'] = (target.id == request.user.id and s['session_key'] == current_key)
        s['remaining'] = _remaining_fa(s['expire_date'], now)

    # ---------------- نشست‌های آزمون (IP / User-Agent) ----------------
    exam_sessions = (ExamSession.objects.filter(student=target)
                     .select_related('exam').order_by('-last_activity')[:30])
    exam_sessions_data = []
    for es in exam_sessions:
        info = parse_user_agent(es.user_agent)
        exam_sessions_data.append({
            'obj': es,
            'exam_title': es.exam.title,
            'ip': es.ip_address or 'ثبت نشده',
            'browser': info['browser'],
            'os': info['os'],
            'device': info['device'],
            'raw_ua': es.user_agent or '',
            'started': es.started_at,
            'last_activity': es.last_activity,
            'last_activity_rel': _relative_fa(es.last_activity, now),
            'is_active': es.is_active,
            'cheat_count': es.cheats.count(),
        })

    # ---------------- دستگاه‌ها و آی‌پی‌های یکتا ----------------
    devices, ips = [], []
    seen_dev, seen_ip = set(), set()
    for row in exam_sessions_data + [{
        'browser': e.browser, 'os': e.os, 'device': e.device, 'ip_address': e.ip_address,
        'created_at': e.created_at
    } for e in SecurityEvent.objects.filter(user=target).order_by('-created_at')[:200]]:
        dev_key = (row.get('device'), row.get('os'), row.get('browser'))
        if any(dev_key) and dev_key not in seen_dev:
            seen_dev.add(dev_key)
            when = row.get('created_at') or row.get('last_activity')
            devices.append({'device': row.get('device') or 'نامشخص', 'os': row.get('os') or 'نامشخص',
                            'browser': row.get('browser') or 'نامشخص', 'last_seen': when,
                            'last_seen_rel': _relative_fa(when, now)})
        ip_val = row.get('ip_address') or row.get('ip')
        if ip_val and ip_val not in seen_ip:
            seen_ip.add(ip_val)
            when = row.get('created_at') or row.get('last_activity')
            ips.append({'ip': ip_val, 'last_seen': when, 'last_seen_rel': _relative_fa(when, now)})

    # ---------------- آزمون‌ها و تلاش‌ها ----------------
    if target.role == 'student':
        exams = (Exam.objects.filter(students=target)
                 .select_related('teacher', 'grade').order_by('-end_time'))
        attempts = {a.exam_id: a for a in ExamAttempt.objects.filter(student=target)}
        exam_rows = []
        for ex in exams:
            att = attempts.get(ex.id)
            row = {
                'exam': ex,
                'attempt': att,
                'status': att.status if att else 'not_started',
                'status_text': att.get_status_display() if att else 'شروع نشده',
                'teacher': ex.teacher.get_full_name() or ex.teacher.username,
                'questions': ex.questions.count(),
                'score': None, 'possible': None, 'percentage': None,
                'submitted_rel': _relative_fa(att.submitted_at, now) if att and att.submitted_at else '—',
            }
            if att and att.status in ('submitted', 'timeout'):
                row['score'], row['possible'], row['percentage'] = _attempt_score(target, ex)
            exam_rows.append(row)

        scored = [r for r in exam_rows if r['percentage'] is not None and r['exam'].show_score_to_student]
        avg_pct = sum(r['percentage'] for r in scored) / len(scored) if scored else 0
        gpa20 = round(avg_pct / 100 * 20, 2)

        activity = {
            'exams_assigned': len(exam_rows),
            'started': sum(1 for r in exam_rows if r['status'] in ('in_progress', 'submitted', 'timeout')),
            'submitted': sum(1 for r in exam_rows if r['status'] == 'submitted'),
            'not_started': sum(1 for r in exam_rows if r['status'] == 'not_started'),
            'average_percentage': round(avg_pct, 1),
            'gpa20': gpa20,
            'answers': StudentAnswer.objects.filter(student=target).count(),
            'graded_answers': StudentAnswer.objects.filter(student=target, score_obtained__isnull=False).count(),
        }
    else:
        if target.role == 'teacher':
            exams = (Exam.objects.filter(teacher=target)
                     .select_related('grade').order_by('-created_at'))
        else:
            exams = Exam.objects.none()
        exam_rows = [{
            'exam': ex, 'attempt': None, 'status': 'teacher', 'status_text': 'برگزارکننده',
            'teacher': '—', 'questions': ex.questions.count(),
            'score': None, 'possible': None, 'percentage': None,
            'submitted_rel': '—',
            'participants': ex.students.count(),
            'submits': ExamAttempt.objects.filter(exam=ex, status='submitted').count(),
        } for ex in exams]
        activity = {
            'exams_assigned': len(exam_rows),
            'started': 0, 'submitted': 0, 'not_started': 0,
            'average_percentage': 0, 'gpa20': 0,
            'answers': 0, 'graded_answers': 0,
            'questions_created': Question.objects.filter(exam__teacher=target).count()
            if target.role == 'teacher' else 0,
        }

    # ---------------- رفتار مشکوک در آزمون ----------------
    cheats = (CheatAttempt.objects.filter(session__student=target)
              .select_related('session__exam').order_by('-created_at')[:20])
    cheats_data = [{
        'type_text': c.get_cheat_type_display(),
        'cheat_type': c.cheat_type,
        'detail': c.detail or '—',
        'exam': c.session.exam.title,
        'ip': c.session.ip_address or '—',
        'when': c.created_at,
        'when_rel': _relative_fa(c.created_at, now),
    } for c in cheats]

    # ---------------- رویدادهای امنیتی ----------------
    events = SecurityEvent.objects.filter(
        Q(user=target) | Q(username_snapshot=target.username)
    ).order_by('-created_at')[:100]
    events_data = [{
        'type_text': e.get_event_type_display(),
        'event_type': e.event_type,
        'severity': e.severity,
        'severity_text': e.get_severity_display(),
        'ip': e.ip_address or '—',
        'device_label': e.device_label,
        'detail': e.detail or '—',
        'when': e.created_at,
        'when_rel': _relative_fa(e.created_at, now),
    } for e in events]

    # ---------------- لاگ فعالیت در آزمون ----------------
    exam_logs = (ExamLog.objects.filter(session__student=target)
                 .select_related('session__exam').order_by('-timestamp')[:20])
    logs_data = [{
        'action': l.action, 'page_url': l.page_url or '—', 'exam': l.session.exam.title,
        'when': l.timestamp, 'when_rel': _relative_fa(l.timestamp, now),
    } for l in exam_logs]

    # ---------------- آخرین رویداد امنیتی برای «آخرین فعالیت» ----------------
    last_event = events[0] if events else None
    last_activity_at = max([d for d in [
        target.last_login,
        last_event.created_at if last_event else None,
        exam_sessions_data[0]['last_activity'] if exam_sessions_data else None,
    ] if d], default=None)

    security_summary = {
        'logins': SecurityEvent.objects.filter(user=target, event_type='login').count(),
        'failed': SecurityEvent.objects.filter(user=target, event_type='login_failed').count(),
        'locked': SecurityEvent.objects.filter(user=target, event_type='login_locked').count(),
        'cheats': CheatAttempt.objects.filter(session__student=target).count(),
        'sessions': len(login_sessions),
        'unique_ips': len(ips),
        'unique_devices': len(devices),
        'risk': 'low',
    }
    if security_summary['locked'] or security_summary['cheats'] >= 3:
        security_summary['risk'] = 'high'
    elif security_summary['failed'] >= 3 or security_summary['cheats']:
        security_summary['risk'] = 'medium'

    password_age_days = None
    if last_event and last_event.event_type == 'password_changed':
        password_age_days = (now - last_event.created_at).days

    context = {
        'u': target,
        'grades': Grade.objects.all(),
        'session_count': len(login_sessions) + len(exam_sessions_data),
        'is_self': target.id == request.user.id,
        'login_sessions': login_sessions,
        'exam_sessions': exam_sessions_data,
        'devices': devices[:8],
        'ips': ips[:10],
        'exam_rows': exam_rows,
        'activity': activity,
        'cheats': cheats_data,
        'events': events_data,
        'logs': logs_data,
        'security': security_summary,
        'password_age_days': password_age_days,
        'last_activity_at': last_activity_at,
        'last_activity_rel': _relative_fa(last_activity_at, now),
        'days_since_joined': (now - target.date_joined).days if target.date_joined else 0,
        'now': now,
    }
    return render(request, 'admin_panel/user_detail.html', context)


@login_required
@require_http_methods(["POST"])
def user_terminate_sessions(request, user_id):
    """پایان همهٔ نشست‌های فعال یک کاربر (خروج اجباری از همه دستگاه‌ها)"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    from django.contrib.sessions.models import Session
    target = get_object_or_404(User, id=user_id)
    now = timezone.now()
    killed = 0
    for s in Session.objects.filter(expire_date__gt=now):
        try:
            data = s.get_decoded()
        except Exception:
            continue
        if str(data.get('_auth_user_id')) != str(target.id):
            continue
        is_current = (target.id == request.user.id and s.session_key == request.session.session_key)
        if is_current:
            continue
        s.delete()
        killed += 1

    # کش «یک نشست برای هر کاربر» هم پاک شود
    cache.delete(f'user_session_{target.id}')

    record_security_event(request, user=request.user, event_type='session_revoked',
                          severity='notice',
                          detail=f'پایان {killed} نشست فعال کاربر «{target.username}» توسط مدیر')
    messages.success(request, f'{killed} نشست فعال پایان یافت.' if killed else 'نشست فعالی پیدا نشد.')
    return redirect('user_detail', user_id=target.id)


@login_required
@require_http_methods(["POST"])
def user_toggle_active(request, user_id):
    """فعال/غیرفعال کردن حساب کاربری (بدون حذف اطلاعات)"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    target = get_object_or_404(User, id=user_id)
    if target.id == request.user.id:
        messages.error(request, 'نمی‌توانید حساب خودتان را غیرفعال کنید.')
        return redirect('user_detail', user_id=target.id)

    target.is_active = not target.is_active
    target.save(update_fields=['is_active'])

    if not target.is_active:
        from django.contrib.sessions.models import Session
        for s in Session.objects.filter(expire_date__gt=timezone.now()):
            try:
                if str(s.get_decoded().get('_auth_user_id')) == str(target.id):
                    s.delete()
            except Exception:
                continue
        cache.delete(f'user_session_{target.id}')

    record_security_event(request, user=request.user, event_type='profile_updated',
                          severity='notice',
                          detail=f'حساب «{target.username}» {"فعال" if target.is_active else "غیرفعال"} شد')
    messages.success(request, 'حساب کاربر غیرفعال شد.' if not target.is_active else 'حساب کاربر فعال شد.')
    return redirect('user_detail', user_id=target.id)


@login_required
@require_http_methods(["POST"])
def user_reset_password(request, user_id):
    """بازنشانی رمز عبور به رمز موقت و اجبار به تغییر آن"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    import secrets
    target = get_object_or_404(User, id=user_id)
    temp = request.POST.get('password', '').strip() or secrets.token_urlsafe(6)
    if len(temp) < 6:
        messages.error(request, 'رمز عبور باید حداقل ۶ کاراکتر باشد.')
        return redirect('user_detail', user_id=target.id)

    target.set_password(temp)
    target.save(update_fields=['password'])
    record_security_event(request, user=request.user, event_type='password_changed',
                          severity='notice',
                          detail=f'بازنشانی رمز عبور «{target.username}» توسط مدیر')
    messages.success(request, f'رمز عبور کاربر «{target.username}» به «{temp}» تغییر یافت.')
    return redirect('user_detail', user_id=target.id)


@login_required
def manage_exams(request):
    """مدیریت آزمون‌ها"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    exams = Exam.objects.all().order_by('-created_at')

    # فیلتر و جستجو
    q = request.GET.get('q', '').strip()
    grade_f = request.GET.get('grade', '').strip()
    status_f = request.GET.get('status', '').strip()
    if q:
        exams = exams.filter(Q(title__icontains=q) | Q(teacher__username__icontains=q) |
                             Q(teacher__first_name__icontains=q) | Q(teacher__last_name__icontains=q))
    if grade_f.isdigit():
        exams = exams.filter(grade_id=int(grade_f))
    if status_f == 'active':
        exams = exams.filter(is_active=True)
    elif status_f == 'inactive':
        exams = exams.filter(is_active=False)

    exams = exams.annotate(
        students_count=Count('students'),
        questions_count=Count('questions')
    )

    grades = Grade.objects.all()

    total_exams = exams.count()
    active_exams = exams.filter(is_active=True).count()
    total_questions = Question.objects.count()

    return render(request, 'admin_panel/manage_exams.html', {
        'exams': exams,
        'grades': grades,
        'total_exams': total_exams,
        'active_exams': active_exams,
        'total_questions': total_questions,
        'q': q,
        'grade_f': grade_f,
        'status_f': status_f,
    })


@login_required
def view_exam_detail(request, exam_id):
    """مشاهده جزئیات یک آزمون"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    exam = get_object_or_404(Exam, id=exam_id)
    questions = exam.questions.all().order_by('order')
    students = exam.students.all()

    total_answers = StudentAnswer.objects.filter(question__exam=exam).count()
    graded_answers = StudentAnswer.objects.filter(question__exam=exam, score_obtained__isnull=False).count()

    context = {
        'exam': exam,
        'questions': questions,
        'students': students,
        'total_answers': total_answers,
        'graded_answers': graded_answers,
    }

    return render(request, 'admin_panel/exam_detail.html', context)


@login_required
def toggle_exam_status(request, exam_id):
    """فعال/غیرفعال کردن آزمون (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    exam = get_object_or_404(Exam, id=exam_id)
    exam.is_active = not exam.is_active
    exam.save()

    return JsonResponse({'success': True, 'is_active': exam.is_active})


@login_required
def delete_exam(request, exam_id):
    """حذف آزمون (AJAX)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    exam = get_object_or_404(Exam, id=exam_id)
    exam.delete()

    return JsonResponse({'success': True})


@login_required
def exam_analytics(request):
    """تحلیل و گزارش‌گیری پیشرفته از آزمون‌ها"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    # فیلترها
    grade_id = request.GET.get('grade')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    exams = Exam.objects.all()

    if grade_id:
        exams = exams.filter(grade_id=grade_id)
    if status == 'active':
        exams = exams.filter(is_active=True)
    elif status == 'inactive':
        exams = exams.filter(is_active=False)
    if date_from:
        exams = exams.filter(created_at__gte=date_from)
    if date_to:
        exams = exams.filter(created_at__lte=date_to)

    exams = exams.annotate(
        students_count=Count('students'),
        attempts_count=Count('examattempt'),
        submitted_count=Count('examattempt', filter=Q(examattempt__status='submitted'))
    )

    grades = Grade.objects.all()

    return render(request, 'admin_panel/exam_analytics.html', {
        'exams': exams,
        'grades': grades,
        'selected_grade': grade_id,
        'selected_status': status,
        'date_from': date_from,
        'date_to': date_to,
    })


@login_required
def student_analytics(request):
    """تحلیل عملکرد دانش‌آموزان"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    # فیلترها
    grade_id = request.GET.get('grade')
    search = request.GET.get('search')

    students = User.objects.filter(role='student')

    if grade_id:
        students = students.filter(grade_id=grade_id)
    if search:
        students = students.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(username__icontains=search) |
            Q(student_code__icontains=search)
        )

    students_data = []
    for student in students:
        total_exams = ExamAttempt.objects.filter(student=student, status='submitted').count()

        total_score = Decimal('0')
        total_possible = Decimal('0')
        for attempt in ExamAttempt.objects.filter(student=student, status='submitted'):
            for question in attempt.exam.questions.all():
                answer = StudentAnswer.objects.filter(student=student, question=question).first()
                total_possible += to_decimal(question.max_score)
                if answer and answer.score_obtained:
                    total_score += to_decimal(answer.score_obtained)

        avg_percentage = float(total_score / total_possible * 100) if total_possible > 0 else 0

        last_attempt = ExamAttempt.objects.filter(student=student).order_by('-submitted_at').first()

        students_data.append({
            'student': student,
            'total_exams': total_exams,
            'avg_percentage': round(avg_percentage, 1),
            'last_activity': last_attempt.submitted_at if last_attempt else None,
        })

    students_data.sort(key=lambda x: x['avg_percentage'], reverse=True)

    grades = Grade.objects.all()

    return render(request, 'admin_panel/student_analytics.html', {
        'students_data': students_data,
        'grades': grades,
        'selected_grade': grade_id,
        'search': search,
    })


# admin_panel/views.py

@login_required
def system_settings(request):
    """تنظیمات سیستم - فقط ادمین"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_report_card':
            show_report_card = 'show_report_card' in request.POST
            SystemSetting.set_setting(
                'show_report_card_to_students',
                'true' if show_report_card else 'false',
                setting_type='report_card',
                description='نمایش کارنامه به دانش‌آموزان'
            )

            min_pass_score = request.POST.get('min_pass_score', '10')
            SystemSetting.set_setting(
                'min_pass_score',
                min_pass_score,
                setting_type='report_card',
                description='حداقل نمره قبولی (از 20)'
            )

            current_semester = request.POST.get('current_semester', 'first')
            SystemSetting.set_setting(
                'current_semester',
                current_semester,
                setting_type='report_card',
                description='نیمسال جاری تحصیلی'
            )

            messages.success(request, 'تنظیمات کارنامه با موفقیت ذخیره شد.')

        elif action == 'save_security':
            enable_anti_cheat = 'enable_anti_cheat' in request.POST
            SystemSetting.set_setting(
                'global_anti_cheat',
                'true' if enable_anti_cheat else 'false',
                setting_type='security',
                description='فعال‌سازی ضد تقلب در همه آزمون‌ها'
            )

            max_tab_switches = request.POST.get('max_tab_switches', '3')
            SystemSetting.set_setting(
                'max_tab_switches',
                max_tab_switches,
                setting_type='security',
                description='حداکثر تعداد تعویض تب مجاز'
            )

            messages.success(request, 'تنظیمات امنیتی با موفقیت ذخیره شد.')

    # دریافت تنظیمات جاری
    show_report_card = SystemSetting.get_setting('show_report_card_to_students', True)
    min_pass_score = SystemSetting.get_setting('min_pass_score', '10')
    current_semester = SystemSetting.get_setting('current_semester', 'first')
    global_anti_cheat = SystemSetting.get_setting('global_anti_cheat', True)
    max_tab_switches = SystemSetting.get_setting('max_tab_switches', '3')

    # این متغیر رو حذف کنید یا اصلاح کنید - قبلاً در template از semester_choices استفاده نشده
    # semester_choices = [
    #     ('first', 'نیمسال اول (مهر تا بهمن)'),
    #     ('second', 'نیمسال دوم (بهمن تا خرداد)'),
    #     ('summer', 'نیمسال تابستان'),
    # ]

    return render(request, 'admin_panel/system_settings.html', {
        'show_report_card': show_report_card,
        'min_pass_score': min_pass_score,
        'current_semester': current_semester,
        'global_anti_cheat': global_anti_cheat,
        'max_tab_switches': max_tab_switches,
        # 'semester_choices': semester_choices,  # این خط رو کامنت کنید یا حذف کنید
    })


# admin_panel/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.db.models import Count, Q
from accounts.models import User, Grade


@login_required
def system_logs(request):
    """مشاهده لاگ‌های سیستم و تقلب‌ها"""
    if request.user.role != 'admin':
        raise PermissionDenied('دسترسی غیرمجاز')

    # دریافت تقلب‌ها با اطلاعات کامل
    cheats = CheatAttempt.objects.all().select_related(
        'session__student',
        'session__exam'
    ).order_by('-created_at')[:100]

    # دریافت لاگ‌های سیستم (با استفاده از فیلد timestamp)
    logs = ExamLog.objects.all().select_related('session__student', 'session__exam').order_by('-timestamp')[:100]

    # آمار تقلب‌ها
    cheat_stats = {
        'total': CheatAttempt.objects.count(),
        'tab_switch': CheatAttempt.objects.filter(cheat_type='tab_switch').count(),
        'copy_paste': CheatAttempt.objects.filter(cheat_type='copy_paste').count(),
        'right_click': CheatAttempt.objects.filter(cheat_type='right_click').count(),
        'multiple_tabs': CheatAttempt.objects.filter(cheat_type='multiple_tabs').count(),
        'today': CheatAttempt.objects.filter(created_at__date=timezone.now().date()).count(),
    }

    # تبدیل تاریخ به شمسی برای نمایش
    def to_jalali(date_val):
        if not date_val:
            return ''
        try:
            import jdatetime
            if timezone.is_naive(date_val):
                date_val = timezone.make_aware(date_val)
            else:
                # ⚠️ تبدیل به منطقه زمانی تهران؛ قبلاً ساعت UTC نمایش داده می‌شد
                date_val = timezone.localtime(date_val)
            jd = jdatetime.datetime.fromgregorian(datetime=date_val)
            return jd.strftime('%Y/%m/%d %H:%M')
        except:
            return date_val.strftime('%Y/%m/%d %H:%M') if date_val else ''

    # آماده‌سازی داده‌های تقلب برای نمایش
    cheats_data = []
    for cheat in cheats:
        cheats_data.append({
            'id': cheat.id,
            'cheat_type': cheat.cheat_type,
            'cheat_type_display': cheat.get_cheat_type_display(),
            'detail': cheat.detail or 'جزئیات ثبت نشده',
            'student_name': cheat.session.student.get_full_name() or cheat.session.student.username,
            'exam_title': cheat.session.exam.title,
            'created_at': to_jalali(cheat.created_at),
        })

    # آماده‌سازی داده‌های لاگ
    logs_data = []
    for log in logs:
        logs_data.append({
            'id': log.id,
            'action': log.action,
            'page_url': log.page_url,
            'student_name': log.session.student.get_full_name() or log.session.student.username,
            'exam_title': log.session.exam.title,
            'timestamp': to_jalali(log.timestamp),
        })

    context = {
        'cheats': cheats_data,
        'logs': logs_data,
        'cheat_stats': cheat_stats,
        'now': timezone.now(),
        'to_jalali': to_jalali,
    }

    return render(request, 'admin_panel/system_logs.html', context)

@login_required
def backup_data(request):
    """بکاپ گرفتن از دیتابیس"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    import subprocess
    import sys
    from django.conf import settings
    import os

    try:
        # ایجاد فایل بکاپ
        timestamp = timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M%S')
        backup_file = f'backup_{timestamp}.json'
        backup_path = os.path.join(settings.BASE_DIR, 'backups', backup_file)

        # اطمینان از وجود پوشه backups
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        # اجرای دستور dumpdata با همان پایتونِ در حال اجرا و مسیر درست پروژه
        with open(backup_path, 'w', encoding='utf-8') as f:
            result = subprocess.run(
                [sys.executable, 'manage.py', 'dumpdata', '--indent=2',
                 '--exclude', 'contenttypes', '--exclude', 'auth.permission'],
                stdout=f,
                stderr=subprocess.PIPE,
                cwd=str(settings.BASE_DIR),
            )

        # اگر خطایی رخ داد، فایل ناقص را پاک کن و خطا را برگردان
        if result.returncode != 0:
            if os.path.exists(backup_path):
                os.remove(backup_path)
            return JsonResponse({
                'error': 'خطا در گرفتن بکاپ: ' + result.stderr.decode('utf-8', 'replace')[-500:]
            }, status=500)

        return JsonResponse({
            'success': True,
            'message': f'بکاپ با موفقیت گرفته شد',
            'file_name': backup_file
        })

    except Exception as e:
        return JsonResponse({'error': f'خطا در گرفتن بکاپ: {str(e)}'}, status=500)


# panel_admin/views.py - اضافه کردن این ویو

@login_required
def exam_cheats_api(request, exam_id):
    """دریافت لیست تقلب‌های یک آزمون (API)"""
    if request.user.role != 'admin':
        return JsonResponse({'error': 'دسترسی ندارید'}, status=403)

    from exams.models import CheatAttempt, ExamSession

    cheats = CheatAttempt.objects.filter(
        session__exam_id=exam_id
    ).select_related('session__student').order_by('-created_at')

    cheats_data = []
    for cheat in cheats:
        cheats_data.append({
            'id': cheat.id,
            'cheat_type': cheat.cheat_type,
            'cheat_type_display': cheat.get_cheat_type_display(),
            'detail': cheat.detail,
            'student_name': cheat.session.student.get_full_name() or cheat.session.student.username,
            'created_at': timezone.localtime(cheat.created_at).strftime('%Y/%m/%d %H:%M:%S'),
        })

    return JsonResponse({'cheats': cheats_data, 'total': len(cheats_data)})
