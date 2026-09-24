# teacher_panel/views.py
# -*- coding: utf-8 -*-

# ========== ایمپورت‌های پایه ==========
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Max, F
from django.db import transaction
from django.core.files.storage import default_storage
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied

# ========== ایمپورت‌های مدل‌ها ==========
from exams.models import (
    BankFolder,
    Exam, Question, StudentAnswer, ExamAttempt,
    ExamSession, CheatAttempt, ExamLog, TeacherAnswer,
    QuestionBank, StudentGroup, Announcement
)
from accounts.models import User, Grade

# ========== ایمپورت‌های جانبی ==========
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
import jdatetime
from django.utils.dateparse import parse_datetime as django_parse_datetime


# ========== توابع کمکی ==========
def to_jalali(date_val):
    """تبدیل تاریخ میلادی به شمسی (بر اساس منطقه زمانی تهران)"""
    if not date_val:
        return ''
    try:
        if isinstance(date_val, str):
            date_val = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
        if timezone.is_naive(date_val):
            date_val = timezone.make_aware(date_val)
        else:
            # ⚠️ بدون این تبدیل، ساعت UTC نمایش داده می‌شد (۳:۳۰ اختلاف با تهران)
            date_val = timezone.localtime(date_val)
        jd = jdatetime.datetime.fromgregorian(datetime=date_val)
        return jd.strftime('%Y/%m/%d %H:%M')
    except Exception:
        return ''


def _normalize_fa_text(value):
    """یکسان‌سازی متن فارسی برای مقایسه پاسخ جاخالی"""
    if value is None:
        return ''
    text = str(value).strip().lower()
    text = text.replace('\u200c', ' ').replace('\u064a', 'ی').replace('\u0643', 'ک').replace('\u0629', 'ه')
    return ' '.join(text.split())


from exams.grading import fill_blank_is_correct  # noqa: E402 — یک پیاده‌سازی مشترک


def _save_to_bank_if_requested(request, question):
    """اگر معلم تیک «ذخیره در بانک سوال» را زده باشد، کپی کامل سوال به بانک می‌رود"""
    if not request.POST.get('save_to_bank'):
        return
    folder = None
    fid = request.POST.get('bank_folder') or ''
    if fid.isdigit():
        folder = BankFolder.objects.filter(id=int(fid), teacher=request.user).first()
    QuestionBank.objects.create(
        teacher=request.user, text=question.text, question_type=question.question_type,
        options=list(question.options or []), options_type=question.options_type or 'text',
        correct_answer=None if question.question_type == 'matching' else question.correct_answer,
        blanks=list(question.blanks or []), matching_pairs=list(question.matching_pairs or []),
        allow_image_answer=question.allow_image_answer, image=question.image or None,
        max_score=question.max_score, folder=folder)


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


def to_int(value, default=0):
    """تبدیل امن ورودی فرم به عدد صحیح (قبلاً مقدار خالی باعث خطای 500 می‌شد)"""
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return default


def parse_form_datetime(value):
    """
    تبدیل رشته تاریخ فرم (datetime-local) به شیء datetime.
    در صورت نامعتبر بودن None برمی‌گرداند تا به‌جای خطای 500، پیام خطا نمایش داده شود.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace('/', '-')
        dt = django_parse_datetime(text)
        if dt is None:
            for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M',
                        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if timezone.is_naive(dt):
        try:
            dt = timezone.make_aware(dt)
        except Exception:
            return None
    return dt


def validate_exam_times(post_data):
    """
    اعتبارسنجی فیلدهای مشترک فرم ساخت/ویرایش آزمون.
    خروجی: (data, errors)
    """
    errors = []

    title = (post_data.get('title') or '').strip()
    if not title:
        errors.append('عنوان آزمون الزامی است.')

    grade_id = post_data.get('grade')
    if not grade_id or not str(grade_id).isdigit():
        errors.append('پایه تحصیلی را انتخاب کنید.')
    elif not Grade.objects.filter(id=int(grade_id)).exists():
        errors.append('پایه تحصیلی انتخاب‌شده معتبر نیست.')

    duration = to_int(post_data.get('duration'), 0)
    if duration <= 0:
        errors.append('مدت آزمون باید عددی بزرگ‌تر از صفر باشد.')
    elif duration > 600:
        errors.append('مدت آزمون نمی‌تواند بیشتر از ۶۰۰ دقیقه باشد.')

    start_time = parse_form_datetime(post_data.get('start_time'))
    end_time = parse_form_datetime(post_data.get('end_time'))

    if not start_time:
        errors.append('زمان شروع آزمون معتبر نیست.')
    if not end_time:
        errors.append('زمان پایان آزمون معتبر نیست.')
    if start_time and end_time and end_time <= start_time:
        errors.append('زمان پایان باید بعد از زمان شروع باشد.')

    timer_type = post_data.get('timer_type', 'floating')
    if timer_type not in dict(Exam.TIMER_TYPE_CHOICES):
        timer_type = 'floating'

    show_questions_mode = post_data.get('show_questions_mode', 'one_by_one')
    if show_questions_mode not in ('all', 'one_by_one'):
        show_questions_mode = 'one_by_one'

    data = {
        'title': title,
        'grade_id': int(grade_id) if (grade_id and str(grade_id).isdigit()) else None,
        'duration_minutes': duration,
        'start_time': start_time,
        'end_time': end_time,
        'timer_type': timer_type,
        'show_questions_mode': show_questions_mode,
        'show_score_to_student': 'show_score' in post_data or 'show_score_to_student' in post_data,
        'show_answers_after_exam': 'show_answers_after_exam' in post_data,
        'enable_anti_cheat': 'enable_anti_cheat' in post_data,
        'prevent_tab_switch': 'prevent_tab_switch' in post_data,
        'prevent_copy_paste': 'prevent_copy_paste' in post_data,
        'track_ip': 'track_ip' in post_data,
        'show_back_button': 'show_back_button' in post_data,
        'allow_teacher_answer': 'allow_teacher_answer' in post_data,
        'random_questions': 'random_questions' in post_data,
        'is_active': 'is_active' in post_data,
    }
    return data, errors


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
        # آمار سریع هر آزمون برای کارت‌های داشبورد
        from django.db.models import Sum
        submitted = ExamAttempt.objects.filter(exam=exam, status__in=['submitted', 'timeout']).count()
        totals = [r['t'] for r in StudentAnswer.objects.filter(
            question__exam=exam, score_obtained__isnull=False
        ).values('student').annotate(t=Sum('score_obtained'))]
        exam.submitted_count = submitted
        exam.avg_total = round(sum(totals) / len(totals), 1) if totals else None
        exam.questions_count = exam.questions.count()

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
        'my_announcements': Announcement.objects.filter(created_by=request.user)[:10],
    })


# ========== مدیریت آزمون ==========
@login_required
def create_exam(request):
    """ساخت آزمون جدید"""
    check_teacher_access(request.user)

    if request.method == 'POST':
        data, errors = validate_exam_times(request.POST)

        if errors:
            # به‌جای خطای 500، فرم با پیام خطا دوباره نمایش داده می‌شود
            local_now = timezone.localtime(timezone.now())
            return render(request, 'teacher_panel/create_exam.html', {
                'grades': Grade.objects.all(),
                'students': User.objects.filter(role='student'),
                'errors': errors,
                'form': request.POST,
                'default_start': request.POST.get('start_time') or local_now.strftime('%Y-%m-%dT%H:%M'),
                'default_end': request.POST.get('end_time') or (local_now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
                'start_jalali': to_jalali(data['start_time'] or local_now),
                'end_jalali': to_jalali(data['end_time'] or (local_now + timedelta(hours=2))),
            }, status=200)

        exam = Exam.objects.create(
            title=data['title'],
            teacher=request.user,
            grade_id=data['grade_id'],
            duration_minutes=data['duration_minutes'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            show_score_to_student=data['show_score_to_student'],
            # ⚠️ این دو گزینه در فرم وجود داشتند ولی ذخیره نمی‌شدند
            show_answers_after_exam=data['show_answers_after_exam'],
            random_questions=data['random_questions'],
            enable_anti_cheat=data['enable_anti_cheat'],
            prevent_tab_switch=data['prevent_tab_switch'],
            prevent_copy_paste=data['prevent_copy_paste'],
            track_ip=data['track_ip'],
            show_questions_mode=data['show_questions_mode'],
            show_back_button=data['show_back_button'],
            allow_teacher_answer=data['allow_teacher_answer'],
            timer_type=data['timer_type'],
        )
        student_ids = [sid for sid in request.POST.getlist('students') if str(sid).isdigit()]
        exam.students.set(student_ids)
        return redirect('edit_exam', exam_id=exam.id)

    # ⚠️ مقادیر پیش‌فرض فرم باید به وقت محلی (تهران) باشند تا با آنچه
    # هنگام ذخیره تفسیر می‌شود یکی باشد (قبلاً ۳:۳۰ اختلاف داشت).
    now = timezone.localtime(timezone.now())
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
    error_msg = None

    def format_datetime(dt):
        """
        مقدار فیلد datetime-local فرم.
        ⚠️ حتماً باید به وقت محلی (تهران) باشد؛ چون هنگام ذخیره، Django مقدار
        بدون timezone را با TIME_ZONE تفسیر می‌کند. قبلاً مقدار UTC در فرم
        نمایش داده می‌شد و با هر بار ذخیره، ساعت آزمون ۳:۳۰ جابه‌جا می‌شد.
        """
        if not dt:
            return ''
        try:
            if timezone.is_aware(dt):
                dt = timezone.localtime(dt)
            return dt.strftime('%Y-%m-%dT%H:%M')
        except:
            return ''

    if request.method == 'POST':
        if 'save_info' in request.POST:
            data, errors = validate_exam_times(request.POST)
            if errors:
                error_msg = ' '.join(errors)
            else:
                exam.title = data['title']
                exam.grade_id = data['grade_id']
                exam.duration_minutes = data['duration_minutes']
                exam.start_time = data['start_time']
                exam.end_time = data['end_time']
                exam.show_score_to_student = data['show_score_to_student']
                exam.is_active = 'is_active' in request.POST
                exam.save()
                success_msg = 'اطلاعات آزمون با موفقیت ذخیره شد'

        elif 'save_settings' in request.POST:
            exam.random_questions = 'random_questions' in request.POST
            exam.show_questions_mode = request.POST.get('show_questions_mode', 'one_by_one')
            if exam.show_questions_mode not in ('all', 'one_by_one'):
                exam.show_questions_mode = 'one_by_one'
            exam.show_back_button = 'show_back_button' in request.POST
            exam.enable_anti_cheat = 'enable_anti_cheat' in request.POST
            exam.prevent_tab_switch = 'prevent_tab_switch' in request.POST
            exam.prevent_copy_paste = 'prevent_copy_paste' in request.POST
            exam.track_ip = 'track_ip' in request.POST
            exam.allow_teacher_answer = 'allow_teacher_answer' in request.POST
            exam.show_answers_after_exam = 'show_answers_after_exam' in request.POST
            exam.timer_type = request.POST.get('timer_type', 'floating')
            if exam.timer_type not in dict(Exam.TIMER_TYPE_CHOICES):
                exam.timer_type = 'floating'
            exam.save()
            success_msg = 'تنظیمات آزمون با موفقیت ذخیره شد'

        elif 'save_students' in request.POST:
            try:
                student_ids = json.loads(request.POST.get('student_ids') or '[]')
                if not isinstance(student_ids, list):
                    raise ValueError
                student_ids = [int(sid) for sid in student_ids if str(sid).isdigit()]
            except (ValueError, TypeError, json.JSONDecodeError):
                student_ids = None

            if student_ids is None:
                error_msg = 'لیست دانش‌آموزان معتبر نیست.'
            else:
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
        'my_groups': StudentGroup.objects.filter(teacher=request.user),
        'selected_student_ids': json.dumps(list(exam.students.values_list('id', flat=True))),
        'success_msg': success_msg,
        'error_msg': error_msg,
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
from exams.question_forms import parse_question_post, apply_to_question, finalize_question  # noqa: E402


def _question_initial(obj=None, post=None):
    """دادهٔ اولیهٔ فرم پویای سوال (برای جاوااسکریپت) از شیء موجود یا POST ناموفق"""
    if post is not None:
        opts = []
        for i in range(1, 7):
            opts.append({'text': post.get('option_%d' % i, ''), 'image': post.get('option_keep_%d' % i, '')})
        blanks = [{'label': post.get('blank_label_%d' % i, ''), 'answer': post.get('blank_answer_%d' % i, '')}
                  for i in range(12) if post.get('blank_label_%d' % i) or post.get('blank_answer_%d' % i)]
        pairs = [{'left': post.get('left_%d' % i, ''), 'right': post.get('right_%d' % i, '')}
                 for i in range(24) if post.get('left_%d' % i) or post.get('right_%d' % i)]
        return {
            'question_type': post.get('question_type', 'multiple_choice'),
            'text': post.get('text', ''), 'max_score': post.get('max_score', ''),
            'options': [o for o in opts if o['text'] or o['image']] or None,
            'correct_answer': post.get('correct_answer', ''),
            'blanks': blanks, 'pairs': pairs,
            'allow_image_answer': bool(post.get('allow_image_answer')),
            'difficulty': post.get('difficulty', 'medium'), 'folder': post.get('folder', ''),
            'image_url': post.get('keep_image_url', ''),
        }
    if obj is None:
        return {'question_type': 'multiple_choice', 'text': '', 'max_score': '1', 'options': None,
                'correct_answer': '', 'blanks': [], 'pairs': [], 'allow_image_answer': False,
                'difficulty': 'medium', 'folder': '', 'image_url': ''}
    from exams.question_forms import _is_image_value
    labels = list(obj.blanks or [])
    answers = [a.strip() for a in (obj.correct_answer or '').replace('،', ',').split(',') if a.strip()] \
        if obj.question_type == 'fill_blank' else []
    n = max(len(labels), len(answers))
    return {
        'question_type': obj.question_type, 'text': obj.text or '',
        'max_score': str(obj.max_score.normalize() if hasattr(obj.max_score, 'normalize') else obj.max_score),
        'options': [{'text': '' if _is_image_value(o) else o, 'image': o if _is_image_value(o) else ''}
                    for o in (obj.options or [])] or None,
        'correct_answer': '' if obj.question_type == 'matching' else (obj.correct_answer or ''),
        'blanks': [{'label': labels[i] if i < len(labels) else '', 'answer': answers[i] if i < len(answers) else ''}
                   for i in range(n)],
        'pairs': list(obj.matching_pairs or []),
        'allow_image_answer': bool(getattr(obj, 'allow_image_answer', False)),
        'difficulty': getattr(obj, 'difficulty', 'medium'),
        'folder': str(getattr(obj, 'folder_id', '') or ''),
        'image_url': obj.image.url if getattr(obj, 'image', None) else '',
    }


def _render_question_form(request, *, mode, action, title, initial, exam=None, obj=None, error=None, status=200):
    ctx = {
        'mode': mode, 'form_action': action, 'form_title': title, 'exam': exam, 'obj': obj,
        'initial': initial, 'form_error': error,
        'type_choices': Question.QUESTION_TYPES,
        'difficulty_choices': QuestionBank.DIFFICULTY_CHOICES,
    }
    if mode == 'bank':
        ctx['folders'] = _folder_tree(request.user)[0]
    if mode == 'exam' and obj is None:
        flat, _, _ = _folder_tree(request.user)
        ctx['folders'] = flat
        ctx['bank_items'] = [{
            'id': b.id, 'text': b.text[:220], 'type': b.question_type, 'type_label': b.get_question_type_display(),
            'score': float(b.max_score), 'difficulty': b.difficulty, 'folder': b.folder_id or 0,
            'folder_name': b.folder.name if b.folder_id else '', 'used': b.use_count,
        } for b in QuestionBank.objects.filter(teacher=request.user).select_related('folder').order_by('folder_id', 'created_at')]
    return render(request, 'teacher_panel/question_form.html', ctx, status=status)


def _apply_question_image(request, obj):
    if request.POST.get('remove_image') and obj.image:
        # فایل حذف نمی‌شود؛ ممکن است بین سوال بانک و سوال آزمون مشترک باشد
        obj.image = None
    if request.FILES.get('image'):
        obj.image = request.FILES['image']


@login_required
def add_question(request, exam_id):
    """افزودن سوال جدید به آزمون (فرم پویای همهٔ انواع + افزودن از بانک سوال)"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)
    action = reverse('add_question', args=[exam.id])
    title = '➕ افزودن سوال به «%s»' % exam.title

    if request.method == 'POST':
        data, err = parse_question_post(request)
        if err:
            messages.error(request, err)
            return _render_question_form(request, mode='exam', action=action, title=title, exam=exam,
                                         initial=_question_initial(post=request.POST), error=err)
        question = Question(exam=exam, order=(exam.questions.aggregate(m=Max('order'))['m'] or 0) + 1)
        apply_to_question(question, data)
        _apply_question_image(request, question)
        question.save()
        finalize_question(question)
        _save_to_bank_if_requested(request, question)
        messages.success(request, 'سوال %d ذخیره شد.' % exam.questions.count())
        if request.POST.get('add_another'):
            return redirect(reverse('add_question', args=[exam.id]) + '?t=' + question.question_type)
        return redirect('edit_exam', exam_id=exam.id)

    initial = _question_initial()
    if request.GET.get('t') in dict(Question.QUESTION_TYPES):
        initial['question_type'] = request.GET['t']
    return _render_question_form(request, mode='exam', action=action, title=title, exam=exam, initial=initial)


@login_required
def edit_question(request, exam_id, question_id):
    """ویرایش سوال آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    question = get_object_or_404(Question, id=question_id, exam=exam)
    check_teacher_access(request.user, exam)
    action = reverse('edit_question', args=[exam.id, question.id])
    title = '✏️ ویرایش سوال %d — %s' % (question.order, exam.title)

    if request.method == 'POST':
        data, err = parse_question_post(request)
        if err:
            messages.error(request, err)
            return _render_question_form(request, mode='exam', action=action, title=title, exam=exam,
                                         obj=question, initial=_question_initial(post=request.POST), error=err)
        apply_to_question(question, data)
        _apply_question_image(request, question)
        question.save()
        finalize_question(question)
        _save_to_bank_if_requested(request, question)
        messages.success(request, 'سوال ویرایش شد.')
        return redirect('edit_exam', exam_id=exam.id)

    return _render_question_form(request, mode='exam', action=action, title=title, exam=exam,
                                 obj=question, initial=_question_initial(question))


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
                if question.question_type in ['true_false', 'multiple_choice']:
                    is_correct = (answer.answer_text.strip().lower() == question.correct_answer.strip().lower())
                elif question.question_type == 'fill_blank':
                    # ✅ پاسخ جاخالی به‌صورت «مقدار۱ | مقدار۲» ذخیره می‌شود
                    is_correct = fill_blank_is_correct(answer.answer_text, question.correct_answer)

            # ========== تبدیل پاسخ matching به متن خوانا ==========
            answer_display = answer.answer_text

            # ========== تبدیل پاسخ جاخالی به متن خوانا ==========
            if question.question_type == 'fill_blank' and answer.answer_text:
                blanks = question.blanks or []
                parts = [p.strip() for p in str(answer.answer_text).split('|')]
                if len(parts) > 1 or blanks:
                    lines = []
                    for i, val in enumerate(parts):
                        label = str(blanks[i]).strip() if i < len(blanks) and blanks[i] else f'جای خالی {i + 1}'
                        lines.append(f'🔹 {label}: {val or "—"}')
                    answer_display = "\n".join(lines)

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
                'auto_graded': bool(answer.auto_graded),
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
            # ✅ JSON امن برای قالب (قبلاً repr پایتون با |safe تزریق می‌شد)
            'matching_pairs_json': json.dumps(question.matching_pairs or [], ensure_ascii=False),
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

    answer = StudentAnswer.objects.filter(id=answer_id).first()
    if not answer:
        return JsonResponse({'success': False, 'error': 'پاسخ یافت نشد'}, status=404)

    # بررسی دسترسی معلم به این پاسخ
    if answer.question.exam.teacher != request.user:
        return JsonResponse({'success': False, 'error': 'شما به این پاسخ دسترسی ندارید'}, status=403)

    # ⚠️ نمره باید به بارم سوال محدود شود؛ قبلاً هر عددی (مثلاً 999) ذخیره می‌شد
    score = validate_decimal_score(request.POST.get('score', 0), max_value=answer.question.max_score)

    answer.score_obtained = score
    answer.graded_by = request.user
    answer.graded_at = timezone.now()
    answer.auto_graded = False  # نمره دستی معلم جای تصحیح خودکار می‌نشیند
    answer.save()

    return JsonResponse({'success': True, 'score': float(score)})


@require_http_methods(["POST"])
@login_required
def save_student_score(request, exam_id, student_id, question_id):
    """ذخیره نمره برای یک سوال خاص (AJAX)"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'داده نامعتبر'}, status=400)

    answer = StudentAnswer.objects.filter(
        student_id=student_id,
        question_id=question_id,
        question__exam_id=exam_id,
    ).first()

    if not answer:
        return JsonResponse({'success': False, 'error': 'پاسخ یافت نشد'}, status=404)

    # بررسی دسترسی معلم
    if answer.question.exam.teacher != request.user:
        return JsonResponse({'success': False, 'error': 'شما به این پاسخ دسترسی ندارید'}, status=403)

    score = validate_decimal_score(data.get('score', 0), max_value=answer.question.max_score)

    answer.score_obtained = score
    answer.graded_by = request.user
    answer.graded_at = timezone.now()
    answer.auto_graded = False  # نمره دستی معلم جای تصحیح خودکار می‌نشیند
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
        'analysis': question_analysis(exam),
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
@login_required
def get_students_api(request):
    """API لیست دانش‌آموزان"""
    # ⚠️ قبلاً بدون احراز هویت بود و اطلاعات همه دانش‌آموزان
    # (نام، کد دانش‌آموزی و پایه) به هر بازدیدکننده‌ای نشان داده می‌شد.
    if request.user.role not in ('teacher', 'admin'):
        raise PermissionDenied('شما به این اطلاعات دسترسی ندارید')

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


def duplicate_exam(request, exam_id):
    """کپی کامل آزمون همراه سوال‌ها و دانش‌آموزها (غیرفعال تا ویرایش معلم)"""
    if request.method != 'POST':
        return redirect('teacher_dashboard')
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)
    questions = list(exam.questions.all())
    students = list(exam.students.all())
    title = exam.title
    exam.pk = None
    exam.title = f'{title} (کپی)'
    exam.is_active = False
    exam.save()
    for q in questions:
        q.pk = None
        q.exam = exam
        q.save()
    exam.students.set(students)
    return redirect('teacher_dashboard')


def export_results_csv(request, exam_id):
    """خروجی اکسل‌پسند (CSV با BOM فارسی) از نتایج آزمون"""
    import csv
    from decimal import Decimal

    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    check_teacher_access(request.user, exam)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="exam-{exam.id}-results.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['ردیف', 'نام دانش‌آموز', 'نام کاربری', 'نمره', 'از مجموع', 'درصد', 'وضعیت', 'زمان ثبت'])

    row = 1
    for student in exam.students.filter(grade=exam.grade):
        total_score = Decimal('0.00')
        total_possible = Decimal('0.00')
        for question in exam.questions.all():
            answer = StudentAnswer.objects.filter(student=student, question=question).first()
            total_possible += Decimal(str(question.max_score))
            if answer and answer.score_obtained is not None:
                total_score += Decimal(str(answer.score_obtained))
        percentage = round(float(total_score / total_possible * 100), 1) if total_possible else 0
        attempt = ExamAttempt.objects.filter(student=student, exam=exam).first()
        status_text = dict(ExamAttempt.STATUS_CHOICES).get(attempt.status, '—') if attempt else '—'
        submitted_at = to_jalali(attempt.submitted_at) if attempt and attempt.submitted_at else '—'
        writer.writerow([row, student.get_full_name(), student.username,
                         float(total_score), float(total_possible), percentage, status_text, submitted_at])
        row += 1
    return response


def question_analysis(exam):
    """تحلیل سوال‌به‌سوال: پاسخ داده‌شده، کاملاً صحیح، درصد موفقیت و میانگین نمره"""
    out = []
    students = exam.students.all()
    for i, q in enumerate(exam.questions.all(), 1):
        answers = StudentAnswer.objects.filter(question=q, student__in=students)
        answered = answers.count()
        full = answers.filter(score_obtained__gte=float(q.max_score)).count() if answered else 0
        scores = [a.score_obtained for a in answers if a.score_obtained is not None]
        rate = round(full / answered * 100) if answered else 0
        out.append({
            'order': i,
            'text': (q.text or '')[:60],
            'type': q.get_question_type_display(),
            'max_score': float(q.max_score),
            'answered': answered,
            'full': full,
            'rate': rate,
            'avg': round(sum(scores) / len(scores), 2) if scores else 0,
        })
    return out


# =====================================================================
# بانک سوال مشترک
# =====================================================================

@login_required
def _parse_bank_payload(request):
    """فیلدهای سوال بانک (همهٔ انواع) + پوشه و سطح دشواری. خروجی: (data, error)"""
    data, err = parse_question_post(request, for_bank=True)
    if err:
        return None, err
    folder = None
    folder_id = request.POST.get('folder') or ''
    if folder_id.isdigit():
        folder = BankFolder.objects.filter(id=int(folder_id), teacher=request.user).first()
    data['folder'] = folder
    difficulty = request.POST.get('difficulty')
    if difficulty in dict(QuestionBank.DIFFICULTY_CHOICES):
        data['difficulty'] = difficulty
    if data['question_type'] == 'matching':
        data['correct_answer'] = None
    return data, None


def question_bank(request):
    """مدیریت بانک سوال معلم + افزودن سوال جدید به بانک"""
    check_teacher_access(request.user)
    if request.method == 'POST':
        data, err = _parse_bank_payload(request)
        if err:
            messages.error(request, err)
            return _render_question_form(request, mode='bank', action=reverse('question_bank'),
                                         title='➕ سوال جدید در بانک', initial=_question_initial(post=request.POST),
                                         error=err)
        bank = QuestionBank(teacher=request.user)
        for k, v in data.items():
            setattr(bank, k, v)
        _apply_question_image(request, bank)
        bank.save()
        messages.success(request, 'سوال به بانک اضافه شد.')
        back = bank.folder_id or ''
        if request.POST.get('stay'):
            return redirect(reverse('bank_question_new') + ('?folder=%s' % back if back else ''))
        return _bank_redirect(request, back)
    folder_id = request.GET.get('folder', '').strip()
    return render(request, 'teacher_panel/question_bank.html',
                  _bank_render_context(request, folder_id))


def _folder_tree(teacher):
    """پوشه‌های معلم به‌صورت درختی (پیمایش عمق‌اول).
    خروجی: (flat_list, by_id, descendants)
      flat_list: هر پوشه با ویژگی‌های depth، own_cnt، cnt (شامل زیرپوشه‌ها) و path
      descendants: {folder_id: set(ids خودش و همهٔ نوادگان)}"""
    folders = list(BankFolder.objects.filter(teacher=teacher)
                   .annotate(own_cnt=Count('questions')).order_by('name'))
    by_id = {f.id: f for f in folders}
    children = {}
    for f in folders:
        pid = f.parent_id if f.parent_id in by_id else None
        children.setdefault(pid, []).append(f)
    flat, descendants = [], {}

    def walk(node, depth, trail, seen):
        node.depth = depth
        node.indent = depth * 18
        node.path = ' / '.join(trail + [node.name])
        node.child_count = len(children.get(node.id, []))
        flat.append(node)
        ids = {node.id}
        for ch in children.get(node.id, []):
            if ch.id in seen:
                continue
            ids |= walk(ch, depth + 1, trail + [node.name], seen | {ch.id})
        descendants[node.id] = ids
        node.cnt = sum(by_id[i].own_cnt for i in ids)
        return ids

    for root in children.get(None, []):
        walk(root, 0, [], {root.id})
    return flat, by_id, descendants


def _bank_render_context(request, folder_id=''):
    flat, by_id, descendants = _folder_tree(request.user)
    all_banks = QuestionBank.objects.filter(teacher=request.user)
    banks = all_banks.select_related('folder')
    current = None
    if folder_id == 'none':
        banks = banks.filter(folder__isnull=True)
    elif folder_id.isdigit() and int(folder_id) in by_id:
        current = by_id[int(folder_id)]
        # سوال‌های خود پوشه + همهٔ زیرپوشه‌ها
        banks = banks.filter(folder_id__in=descendants[current.id])

    q = (request.GET.get('q') or '').strip()
    qtype = request.GET.get('type', '')
    diff = request.GET.get('difficulty', '')
    if q:
        banks = banks.filter(Q(text__icontains=q) | Q(correct_answer__icontains=q))
    if qtype:
        banks = banks.filter(question_type=qtype)
    if diff:
        banks = banks.filter(difficulty=diff)

    if current:
        subfolders = [f for f in flat if f.parent_id == current.id]
        breadcrumb = [by_id[a.id] for a in current.ancestors() if a.id in by_id]
    else:
        subfolders = [f for f in flat if f.depth == 0] if folder_id != 'none' else []
        breadcrumb = []

    type_stats = {k: 0 for k, _ in QuestionBank._meta.get_field('question_type').choices}
    for row in all_banks.values('question_type').annotate(n=Count('id')):
        type_stats[row['question_type']] = row['n']

    return {
        'banks': banks,
        'folders': flat,
        'folder_id': folder_id,
        'current_folder': current,
        'subfolders': subfolders,
        'breadcrumb': breadcrumb,
        'unfiled_count': all_banks.filter(folder__isnull=True).count(),
        'total_count': all_banks.count(),
        'exams': Exam.objects.filter(teacher=request.user),
        'type_choices': QuestionBank._meta.get_field('question_type').choices,
        'difficulty_choices': QuestionBank.DIFFICULTY_CHOICES,
        'type_stats': [(label, type_stats.get(k, 0)) for k, label in
                       QuestionBank._meta.get_field('question_type').choices],
        'q': q, 'qtype': qtype, 'diff': diff,
        'filtered': bool(q or qtype or diff),
    }


def _bank_redirect(request, folder_id=None):
    """بازگشت به همان پوشه‌ای که کاربر در آن بود"""
    nxt = request.POST.get('next') or ''
    if nxt.startswith('/teacher/') and '//' not in nxt:
        return redirect(nxt)
    fid = folder_id if folder_id is not None else (request.POST.get('back') or '')
    url = reverse('question_bank')
    return redirect(url + ('?folder=%s' % fid if str(fid).strip() else ''))


def _get_parent_folder(request, raw):
    raw = (raw or '').strip()
    if raw.isdigit():
        return get_object_or_404(BankFolder, id=int(raw), teacher=request.user)
    return None


@login_required
@require_http_methods(["POST"])
def bank_folder_add(request):
    """ساخت پوشه یا زیرپوشه در بانک سوال"""
    check_teacher_access(request.user)
    name = (request.POST.get('name') or '').strip()[:80]
    parent = _get_parent_folder(request, request.POST.get('parent'))
    if not name:
        messages.error(request, 'نام پوشه الزامی است.')
    elif BankFolder.objects.filter(teacher=request.user, parent=parent, name=name).exists():
        messages.error(request, 'پوشه‌ای با این نام در همین مسیر دارید.')
    else:
        folder = BankFolder.objects.create(teacher=request.user, name=name, parent=parent)
        messages.success(request, 'پوشه «%s» ساخته شد.' % folder.full_path)
    return _bank_redirect(request, parent.id if parent else '')


@login_required
@require_http_methods(["POST"])
def bank_folder_rename(request, folder_id):
    """تغییر نام و/یا جابجایی پوشه (تغییر والد)"""
    check_teacher_access(request.user)
    folder = get_object_or_404(BankFolder, id=folder_id, teacher=request.user)
    name = (request.POST.get('name') or '').strip()[:80]
    parent = folder.parent
    if 'parent' in request.POST:
        parent = _get_parent_folder(request, request.POST.get('parent'))
        if parent is not None:
            _, _, descendants = _folder_tree(request.user)
            if parent.id in descendants.get(folder.id, {folder.id}):
                messages.error(request, 'پوشه را نمی‌توان داخل خودش یا زیرپوشه‌هایش برد.')
                return _bank_redirect(request)
    if not name:
        messages.error(request, 'نام پوشه الزامی است.')
    elif BankFolder.objects.filter(teacher=request.user, parent=parent, name=name).exclude(id=folder.id).exists():
        messages.error(request, 'پوشه‌ای با این نام در همین مسیر دارید.')
    else:
        folder.name = name
        folder.parent = parent
        folder.save()
        messages.success(request, 'پوشه به‌روزرسانی شد.')
    return _bank_redirect(request)


@login_required
@require_http_methods(["POST"])
def bank_folder_delete(request, folder_id):
    """حذف پوشه؛ سوال‌ها و زیرپوشه‌ها به پوشهٔ والد منتقل می‌شوند (چیزی پاک نمی‌شود)"""
    check_teacher_access(request.user)
    folder = get_object_or_404(BankFolder, id=folder_id, teacher=request.user)
    parent = folder.parent
    name = folder.name
    with transaction.atomic():
        QuestionBank.objects.filter(folder=folder).update(folder=parent)
        for child in folder.children.all():
            new_name, i = child.name, 2
            while BankFolder.objects.filter(teacher=request.user, parent=parent, name=new_name).exists():
                new_name = '%s (%d)' % (child.name, i)
                i += 1
            child.name, child.parent = new_name, parent
            child.save()
        folder.delete()
    where = 'پوشهٔ «%s»' % parent.name if parent else 'ریشه بانک'
    messages.success(request, 'پوشه «%s» حذف شد؛ محتوایش به %s رفت.' % (name, where))
    return _bank_redirect(request, parent.id if parent else '')


def _copy_bank_to_exam(bank, exam, order):
    q = Question.objects.create(
        exam=exam, text=bank.text, question_type=bank.question_type,
        options=list(bank.options or []), options_type=bank.options_type or 'text',
        correct_answer=bank.correct_answer, blanks=list(bank.blanks or []),
        matching_pairs=list(bank.matching_pairs or []), allow_image_answer=bank.allow_image_answer,
        image=bank.image or None, max_score=bank.max_score, order=order)
    finalize_question(q)
    return q


@login_required
@require_http_methods(["POST"])
def bank_folder_import(request, folder_id):
    """افزودن همهٔ سوال‌های یک پوشه (و زیرپوشه‌هایش) به یک آزمون"""
    check_teacher_access(request.user)
    folder = get_object_or_404(BankFolder, id=folder_id, teacher=request.user)
    exam = get_object_or_404(Exam, id=request.POST.get('exam_id') or 0, teacher=request.user)
    _, _, descendants = _folder_tree(request.user)
    banks = list(QuestionBank.objects.filter(teacher=request.user,
                                             folder_id__in=descendants.get(folder.id, {folder.id}))
                 .order_by('folder_id', 'created_at'))
    with transaction.atomic():
        order = exam.questions.aggregate(m=Max('order'))['m'] or 0
        for b in banks:
            order += 1
            _copy_bank_to_exam(b, exam, order)
        QuestionBank.objects.filter(id__in=[b.id for b in banks]).update(use_count=F('use_count') + 1)
    messages.success(request, '%d سوال از پوشه «%s» به آزمون «%s» اضافه شد.' % (len(banks), folder.name, exam.title))
    return _bank_redirect(request, folder.id)


@login_required
@require_http_methods(["POST"])
def bank_seed_sample(request):
    """بارگذاری بانک سوال نمونهٔ پوشه‌بندی‌شده برای معلم جاری (قابل تکرار، بدون تکراری)"""
    check_teacher_access(request.user)
    from exams.bank_seed import seed_question_bank
    nf, nq = seed_question_bank(request.user)
    if nq or nf:
        messages.success(request, 'بانک نمونه بارگذاری شد: %d پوشه و %d سوال جدید.' % (nf, nq))
    else:
        messages.info(request, 'بانک نمونه از قبل کامل بارگذاری شده است.')
    return redirect('question_bank')


@login_required
@require_http_methods(["POST"])
def bank_bulk_action(request):
    """عملیات گروهی روی سوال‌های انتخاب‌شده: جابجایی، افزودن به آزمون، حذف"""
    check_teacher_access(request.user)
    ids = [int(i) for i in request.POST.getlist('ids') if str(i).isdigit()]
    banks = QuestionBank.objects.filter(teacher=request.user, id__in=ids)
    n = banks.count()
    action = request.POST.get('action', '')
    if not n:
        messages.error(request, 'هیچ سوالی انتخاب نشده است.')
    elif action == 'move':
        target = _get_parent_folder(request, request.POST.get('folder'))
        banks.update(folder=target)
        messages.success(request, '%d سوال به %s منتقل شد.' % (n, '«%s»' % target.name if target else 'ریشه'))
    elif action == 'import':
        exam = get_object_or_404(Exam, id=request.POST.get('exam_id') or 0, teacher=request.user)
        with transaction.atomic():
            order = exam.questions.aggregate(m=Max('order'))['m'] or 0
            for b in banks.order_by('created_at'):
                order += 1
                _copy_bank_to_exam(b, exam, order)
            banks.update(use_count=F('use_count') + 1)
        messages.success(request, '%d سوال به آزمون «%s» اضافه شد.' % (n, exam.title))
    elif action == 'delete':
        banks.delete()
        messages.success(request, '%d سوال از بانک حذف شد.' % n)
    else:
        messages.error(request, 'عملیات نامعتبر است.')
    return _bank_redirect(request)


@login_required
@require_http_methods(["POST"])
def bank_question_edit(request, bank_id):
    """ویرایش یک سوال موجود در بانک سوال"""
    check_teacher_access(request.user)
    bank = get_object_or_404(QuestionBank, id=bank_id, teacher=request.user)
    data, err = _parse_bank_payload(request)
    if err:
        messages.error(request, err)
        return _render_question_form(request, mode='bank', action=reverse('bank_question_edit', args=[bank.id]),
                                     title='✏️ ویرایش سوال بانک', obj=bank,
                                     initial=_question_initial(post=request.POST), error=err)
    for key, value in data.items():
        setattr(bank, key, value)
    _apply_question_image(request, bank)
    bank.save()
    messages.success(request, 'سوال ویرایش شد.')
    return _bank_redirect(request, bank.folder_id or '')


@login_required
def bank_question_new(request):
    """صفحهٔ فرم سوال جدید بانک"""
    check_teacher_access(request.user)
    initial = _question_initial()
    initial['folder'] = request.GET.get('folder', '')
    return _render_question_form(request, mode='bank', action=reverse('question_bank'),
                                 title='➕ سوال جدید در بانک', initial=initial)


@login_required
def bank_question_form(request, bank_id):
    """صفحهٔ فرم ویرایش سوال بانک"""
    check_teacher_access(request.user)
    bank = get_object_or_404(QuestionBank, id=bank_id, teacher=request.user)
    return _render_question_form(request, mode='bank', action=reverse('bank_question_edit', args=[bank.id]),
                                 title='✏️ ویرایش سوال بانک', obj=bank, initial=_question_initial(bank))


@login_required
@require_http_methods(["POST"])
def bank_question_move(request, bank_id):
    """جابجایی سوال بانک بین پوشه‌ها"""
    check_teacher_access(request.user)
    bank = get_object_or_404(QuestionBank, id=bank_id, teacher=request.user)
    folder_id = request.POST.get('folder') or ''
    if folder_id and folder_id.isdigit():
        bank.folder = get_object_or_404(BankFolder, id=int(folder_id), teacher=request.user)
    else:
        bank.folder = None
    bank.save()
    messages.success(request, 'سوال جابجا شد.')
    return _bank_redirect(request)


@login_required
@require_http_methods(["POST"])
def delete_bank_question(request, bank_id):
    bank = get_object_or_404(QuestionBank, id=bank_id, teacher=request.user)
    bank.delete()
    messages.success(request, 'سوال بانکی حذف شد.')
    return _bank_redirect(request)


@login_required
@require_http_methods(["POST"])
def import_bank_question(request, bank_id):
    """کپی سوال بانکی به انتهای سوالات یک آزمون"""
    bank = get_object_or_404(QuestionBank, id=bank_id, teacher=request.user)
    exam = get_object_or_404(Exam, id=request.POST.get('exam_id'), teacher=request.user)
    last = exam.questions.aggregate(m=Max('order'))['m'] or 0
    _copy_bank_to_exam(bank, exam, last + 1)
    bank.use_count += 1
    bank.save(update_fields=['use_count'])
    messages.success(request, f'سوال به آزمون «{exam.title}» اضافه شد.')
    return _bank_redirect(request)


# =====================================================================
# گروه‌های دانش‌آموزی
# =====================================================================

@login_required
def groups(request):
    """مدیریت کلاس/گروه دانش‌آموزی + ویرایش اعضا"""
    check_teacher_access(request.user)
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            name = (request.POST.get('name') or '').strip()
            if not name:
                messages.error(request, 'نام گروه الزامی است.')
            else:
                g = StudentGroup.objects.create(teacher=request.user, name=name)
                g.students.set(User.objects.filter(id__in=request.POST.getlist('students'), role='student'))
                messages.success(request, 'گروه ساخته شد.')
        elif action == 'save':
            g = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), teacher=request.user)
            g.students.set(User.objects.filter(id__in=request.POST.getlist('students'), role='student'))
            messages.success(request, 'اعضای گروه به‌روزرسانی شد.')
        elif action == 'delete':
            g = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), teacher=request.user)
            g.delete()
            messages.success(request, 'گروه حذف شد.')
        return redirect('groups')
    my_groups = StudentGroup.objects.filter(teacher=request.user).prefetch_related('students')
    return render(request, 'teacher_panel/groups.html', {
        'groups': my_groups,
        'students': User.objects.filter(role='student').order_by('username'),
    })


@login_required
@require_http_methods(["POST"])
def apply_group_to_exam(request, exam_id):
    """افزودن همه دانش‌آموزان یک گروه به آزمون"""
    exam = get_object_or_404(Exam, id=exam_id, teacher=request.user)
    group = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), teacher=request.user)
    exam.students.add(*group.students.all())
    messages.success(request, f'گروه «{group.name}» به آزمون اضافه شد.')
    return redirect('edit_exam_info', exam_id=exam.id)


# =====================================================================
# اطلاعیه‌ها
# =====================================================================

@login_required
@require_http_methods(["POST"])
def announcement_create(request):
    title = (request.POST.get('title') or '').strip()
    if not title:
        messages.error(request, 'عنوان اطلاعیه الزامی است.')
        return redirect(request.POST.get('back') or 'teacher_dashboard')
    grade_id = request.POST.get('grade') or None
    Announcement.objects.create(
        created_by=request.user, title=title,
        body=(request.POST.get('body') or '').strip(),
        grade_id=grade_id if str(grade_id).isdigit() else None)
    messages.success(request, 'اطلاعیه منتشر شد.')
    return redirect(request.POST.get('back') or 'teacher_dashboard')


@login_required
@require_http_methods(["POST"])
def announcement_delete(request, ann_id):
    ann = get_object_or_404(Announcement, id=ann_id)
    if ann.created_by_id != request.user.id and request.user.role != 'admin':
        raise PermissionDenied('فقط نویسنده یا مدیر می‌تواند اطلاعیه را حذف کند')
    ann.delete()
    messages.success(request, 'اطلاعیه حذف شد.')
    return redirect(request.POST.get('back') or 'teacher_dashboard')
