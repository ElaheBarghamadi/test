from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

from exams.models import Question, StudentAnswer, TeacherAnswer

# ========== محدودیت تلاش ورود (ضد بروت‌فورس) ==========
LOGIN_MAX_FAILS_USER = 7          # تعداد تلاش ناموفق برای هر نام کاربری
LOGIN_MAX_FAILS_IP = 25           # تعداد تلاش ناموفق برای هر IP
LOGIN_LOCK_SECONDS = 15 * 60      # مدت قفل شدن
LOGIN_WINDOW_SECONDS = 15 * 60


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        first = forwarded.split(',')[0].strip()
        if first:
            return first
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _login_locked(request, username):
    ip = _client_ip(request)
    user_count = cache.get(f'login:fail:user:{username}', 0)
    ip_count = cache.get(f'login:fail:ip:{ip}', 0)
    return user_count >= LOGIN_MAX_FAILS_USER or ip_count >= LOGIN_MAX_FAILS_IP


def _login_register_fail(request, username):
    ip = _client_ip(request)
    cache.add(f'login:fail:user:{username}', 0, LOGIN_WINDOW_SECONDS)
    cache.add(f'login:fail:ip:{ip}', 0, LOGIN_WINDOW_SECONDS)
    try:
        cache.incr(f'login:fail:user:{username}')
        cache.incr(f'login:fail:ip:{ip}')
    except ValueError:
        pass


def _login_clear_fails(username):
    cache.delete(f'login:fail:user:{username}')


def login_view(request):
    """صفحه ورود یکسان برای همه نقش‌ها"""
    # اگر کاربر وارد شده بود، بره به پنل خودش
    if request.user.is_authenticated:
        if request.user.role == 'admin':
            return redirect('admin_dashboard')
        elif request.user.role == 'teacher':
            return redirect('teacher_dashboard')
        elif request.user.role == 'student':
            return redirect('student_dashboard')
        return redirect('/')

    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()[:150]
        password = request.POST.get('password') or ''

        # ⚠️ قفل موقت پس از تلاش‌های ناموفق متعدد
        if _login_locked(request, username):
            return render(request, 'login.html', {
                'error': 'تعداد تلاش‌های ناموفق زیاد بود. لطفاً چند دقیقه دیگر دوباره تلاش کنید.',
                'locked': True,
            }, status=429)

        user = authenticate(request, username=username, password=password)

        if user is not None:
            _login_clear_fails(username)
            auth_login(request, user)

            # هدایت بر اساس نقش
            if user.role == 'admin':
                return redirect('admin_dashboard')
            elif user.role == 'teacher':
                return redirect('teacher_dashboard')
            elif user.role == 'student':
                return redirect('student_dashboard')
            return redirect('/')
        else:
            _login_register_fail(request, username)
            return render(request, 'login.html', {'error': 'نام کاربری یا رمز عبور اشتباه است'})

    return render(request, 'login.html')


@require_http_methods(["POST"])
def logout_view(request):
    """خروج از سیستم — فقط با درخواست POST (جلوگیری از خروج اجباری با لینک مخرب)"""
    logout(request)
    return redirect('login')


# ========== سرویس فایل‌های رسانه با احراز دسترسی ==========
def _serve(path):
    from django.conf import settings as dj_settings
    import os
    full = os.path.join(dj_settings.MEDIA_ROOT, path)
    real_root = os.path.realpath(dj_settings.MEDIA_ROOT)
    real_full = os.path.realpath(full)
    # جلوگیری از فرار از مسیر (path traversal)
    if not real_full.startswith(real_root + os.sep) or not os.path.isfile(real_full):
        raise Http404('فایل یافت نشد')
    response = FileResponse(open(real_full, 'rb'))
    response['Cache-Control'] = 'private, max-age=600'
    return response


def _exam_of_question_image(path):
    q = Question.objects.filter(image=path).select_related('exam').first()
    return q.exam if q else None


def _exam_of_student_answer(path):
    a = StudentAnswer.objects.filter(answer_image=path).select_related(
        'question__exam', 'student').first()
    return a


def _exam_of_teacher_answer(path):
    t = TeacherAnswer.objects.filter(answer_image=path).select_related('question__exam').first()
    return t


@login_required
def protected_media(request, path):
    """دسترسی به فایل‌های آپلودشده فقط برای افراد مجاز

    - تصاویر سوالات: معلم سازنده + دانش‌آموزانِ همان آزمون + مدیر
    - تصاویر پاسخ دانش‌آموز: خود دانش‌آموز + معلم آن آزمون + مدیر
    - تصاویر پاسخ تشریحی معلم: معلم + دانش‌آموزان (پس از اعلام نتیجه) + مدیر
    """
    user = request.user
    path = path.lstrip('/')

    if user.role == 'admin':
        return _serve(path)

    if path.startswith('question_images/'):
        exam = _exam_of_question_image(path)
        if exam is None:
            raise Http404('فایل یافت نشد')
        if exam.teacher_id == user.id:
            return _serve(path)
        if user.role == 'student' and user.grade_id == exam.grade_id \
                and exam.students.filter(pk=user.pk).exists():
            return _serve(path)
        return HttpResponseForbidden('دسترسی به این فایل مجاز نیست')

    if path.startswith('student_answers/'):
        answer = _exam_of_student_answer(path)
        if answer is None:
            raise Http404('فایل یافت نشد')
        if answer.student_id == user.id:
            return _serve(path)
        if answer.question.exam.teacher_id == user.id:
            return _serve(path)
        if user.role == 'admin':
            return _serve(path)
        return HttpResponseForbidden('دسترسی به این فایل مجاز نیست')

    if path.startswith('teacher_answers/'):
        teacher_answer = _exam_of_teacher_answer(path)
        if teacher_answer is None:
            raise Http404('فایل یافت نشد')
        exam = teacher_answer.question.exam
        if exam.teacher_id == user.id:
            return _serve(path)
        if user.role == 'student' and exam.show_answers_after_exam \
                and exam.students.filter(pk=user.pk).exists():
            return _serve(path)
        return HttpResponseForbidden('دسترسی به این فایل مجاز نیست')

    raise Http404('فایل یافت نشد')


# ========== صفحات خطا ==========

def bad_request(request, exception=None):
    """خطای 400 - درخواست نادرست"""
    return render(request, '400.html', status=400)


def permission_denied(request, exception=None):
    """خطای 403 - دسترسی غیرمجاز"""
    return render(request, '403.html', status=403)


def page_not_found(request, exception=None):
    """خطای 404 - صفحه یافت نشد"""
    return render(request, '404.html', status=404)


def server_error(request):
    """خطای 500 - خطای داخلی سرور"""
    return render(request, '500.html', status=500)
