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

_FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

ERROR_PAGES = {
    400: {'title': 'درخواست قابل پردازش نبود',
          'message': 'اطلاعات ارسال‌شده ناقص یا نادرست بود. معمولاً با تازه‌کردن صفحه و تلاش دوباره حل می‌شود.',
          'tips': ['صفحه را تازه کنید و دوباره امتحان کنید.', 'اگر از لینکی آمده‌اید، آدرس آن را بررسی کنید.'],
          'accent': '#e0a526', 'primary_label': '↻ تلاش دوباره'},
    403: {'title': 'به این صفحه دسترسی ندارید',
          'message': 'این بخش برای نقش کاربری شما در دسترس نیست یا مربوط به حساب دیگری است.',
          'tips': ['مطمئن شوید با حساب درست وارد شده‌اید.', 'اگر فکر می‌کنید باید دسترسی داشته باشید، با مدیر سامانه تماس بگیرید.'],
          'accent': '#e05a4f', 'primary_label': '🏠 رفتن به صفحهٔ من'},
    404: {'title': 'این صفحه پیدا نشد',
          'message': 'ممکن است آدرس اشتباه تایپ شده باشد، یا این آزمون و صفحه حذف یا جابه‌جا شده باشد.',
          'tips': ['آدرس را دوباره بررسی کنید.', 'از منوی صفحهٔ اصلی به بخش موردنظر بروید.'],
          'accent': '#2ec4b6', 'primary_label': '🏠 رفتن به صفحهٔ من'},
    405: {'title': 'این کار از این راه ممکن نیست',
          'message': 'این عملیات فقط از داخل فرم مربوط به خودش انجام می‌شود، نه با باز کردن مستقیم آدرس.',
          'tips': ['به صفحهٔ قبل برگردید و از دکمهٔ مربوط استفاده کنید.'],
          'accent': '#8b6cf0', 'primary_label': '🏠 رفتن به صفحهٔ من'},
    500: {'title': 'مشکلی در سرور پیش آمد',
          'message': 'تقصیر شما نیست؛ خطا ثبت شد. اگر وسط آزمون هستید نگران نباشید — پاسخ‌های ذخیره‌شده از بین نمی‌روند.',
          'tips': ['چند لحظه صبر کنید و صفحه را تازه کنید.', 'اگر مشکل ادامه داشت، به معلم یا مدیر سامانه اطلاع دهید.'],
          'accent': '#e05a4f', 'primary_label': '↻ تلاش دوباره'},
    'csrf': {'title': 'اعتبار صفحه تمام شده است',
             'message': 'این صفحه مدت زیادی باز مانده یا از تب دیگری خارج شده‌اید؛ برای امنیت، فرم پذیرفته نشد.',
             'tips': ['صفحه را تازه کنید و دوباره ارسال کنید.', 'اگر خارج شده‌اید، دوباره وارد حساب شوید.'],
             'accent': '#e0a526', 'primary_label': '↻ تازه‌کردن صفحه'},
}


def _home_url(request):
    """آدرس صفحهٔ اصلی هر نقش — بدون کوئری اضافه و بدون احتمال خطا"""
    try:
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            return {'admin': '/admin-panel/', 'teacher': '/teacher/dashboard/'}.get(
                getattr(user, 'role', ''), '/student/dashboard/')
    except Exception:
        pass
    return '/login/'


def render_error(request, code, status=None):
    """صفحهٔ خطای مستقل؛ بدون base.html و context processorها تا در خطای ۵۰۰ (مثلاً قطعی دیتابیس) خودش خراب نشود"""
    from django.http import HttpResponse
    from django.template import loader
    info = ERROR_PAGES[code]
    status = status or (403 if code == 'csrf' else code)
    home = _home_url(request)
    ctx = dict(info, code=status, code_fa=str(status).translate(_FA_DIGITS), home_url=home,
               primary_url=None if info['primary_label'].startswith('↻') else home,
               request_path=getattr(request, 'path', '') if status == 404 else '')
    try:
        html = loader.get_template('errors/error.html').render(ctx)
    except Exception:
        html = '<h1 style="font-family:tahoma;text-align:center;margin-top:20vh">خطای %s</h1>' % status
    return HttpResponse(html, status=status)


def bad_request(request, exception=None):
    return render_error(request, 400)


def permission_denied(request, exception=None):
    return render_error(request, 403)


def page_not_found(request, exception=None):
    return render_error(request, 404)


def server_error(request):
    return render_error(request, 500)


def csrf_failure(request, reason=''):
    return render_error(request, 'csrf')
