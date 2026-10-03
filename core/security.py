# -*- coding: utf-8 -*-
"""
core.security — لایهٔ مرکزی «اعتبارسنجی ورودی‌ها قبل از ثبت» و «محدودسازی نرخ درخواست»

اصول:
۱) هیچ مقدار کاربر مستقیم ذخیره نمی‌شود؛ همهٔ ورودی‌ها از clean_* عبور می‌کنند.
۲) پیام‌های خطا فارسی و قابل نمایش به کاربر هستند.
۳) هیچ تابعی در این ماژول نباید استثنا به بیرون بدهد؛ یا (مقدار، None) یا (مقدار پیش‌فرض، پیام خطا).
"""
import re
import unicodedata
from functools import wraps

from django.core.cache import cache
from django.http import JsonResponse
from django.contrib import messages

# ---------------------------- پاک‌سازی متن ----------------------------

# کنترل‌کاراکترها (به‌جز newline/tab) و کاراکترهای صفرعرض و جهت‌دهی یونیکد
_RE_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_RE_ZERO_WIDTH = re.compile(r'[\u200b\u200e\u200f\u2060\ufeff]')
_RE_WS = re.compile(r'[ \t\u00a0]+')

MAX_TEXT = 10000          # سقف مطلق متن آزاد (پاسخ تشریحی و…)
MAX_TITLE = 200
MAX_NAME = 60


def clean_text(value, max_len=MAX_TITLE, min_len=0, required=False,
               label='این فیلد', collapse=True, allow_newline=True):
    """پاک‌سازی متن آزاد: حذف کنترل‌کاراکتر/صفرعرض، نرمال‌سازی یونیکد، برش طول.

    خروجی: (متن_پاک‌شده, پیام_خطا یا None)
    """
    if value is None:
        value = ''
    text = str(value)
    text = _RE_CONTROL.sub('', text)
    text = _RE_ZERO_WIDTH.sub('', text)
    text = unicodedata.normalize('NFC', text)
    if not allow_newline:
        text = text.replace('\r', ' ').replace('\n', ' ')
    else:
        text = text.replace('\r\n', '\n').replace('\r', '\n')
    if collapse:
        if allow_newline:
            text = '\n'.join(_RE_WS.sub(' ', ln).strip() for ln in text.split('\n'))
            text = re.sub(r'\n{3,}', '\n\n', text)
        else:
            text = _RE_WS.sub(' ', text).strip()
    text = text.strip()

    if len(text) > max_len:
        return text[:max_len].strip(), f'{label} نباید بیشتر از {max_len} نویسه باشد.'
    if required and len(text) < max(min_len, 1):
        return '', f'{label} الزامی است.'
    if len(text) < min_len:
        return text, f'{label} باید حداقل {min_len} نویسه باشد.'
    return text, None


def clean_int(value, lo=None, hi=None, default=None, label='عدد'):
    """تبدیل امن به عدد صحیح همراه با بازهٔ مجاز."""
    try:
        num = int(float(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return default, f'{label} باید یک عدد باشد.'
    if lo is not None and num < lo:
        return default, f'{label} نمی‌تواند کمتر از {lo} باشد.'
    if hi is not None and num > hi:
        return default, f'{label} نمی‌تواند بیشتر از {hi} باشد.'
    return num, None


def clean_choice(value, choices, default=None, label='این مورد'):
    """انتبارسنجی مقدار انتخابی در برابر فهرست مجاز."""
    allowed = set(choices)
    if value in allowed:
        return value, None
    return default, f'{label} معتبر نیست.'


# ---------------------------- نام کاربری و رمز ----------------------------

USERNAME_RE = re.compile(r'^[a-zA-Z0-9_.@-]+$')


def clean_username(value, required=True):
    """نام کاربری: ۳ تا ۱۵۰ نویسه از الفبای محدود (بدون فاصله و کنترل)."""
    text, err = clean_text(value, max_len=150, min_len=3, required=required,
                           label='نام کاربری', collapse=False, allow_newline=False)
    if err:
        return '', err
    if not USERNAME_RE.match(text):
        return '', 'نام کاربری فقط می‌تواند شامل حروف انگلیسی، عدد و _.@- باشد.'
    return text, None


def password_policy(pwd):
    """سیاست رمز عبور: حداقل ۸ نویسه، شامل حرف و عدد؛ بدون فاصله.

    خروجی: پیام خطا یا None
    """
    pwd = pwd or ''
    if len(pwd) < 8:
        return 'رمز عبور باید حداقل ۸ نویسه باشد.'
    if len(pwd) > 128:
        return 'رمز عبور نباید بیشتر از ۱۲۸ نویسه باشد.'
    if ' ' in pwd:
        return 'رمز عبور نباید فاصله داشته باشد.'
    if not re.search(r'[a-zA-Z\u0600-\u06FF]', pwd):
        return 'رمز عبور باید دست‌کم یک حرف داشته باشد.'
    if not re.search(r'\d', pwd):
        return 'رمز عبور باید دست‌کم یک رقم داشته باشد.'
    return None


STUDENT_CODE_RE = re.compile(r'^[A-Za-z0-9-]{3,20}$')


def clean_student_code(value):
    text, err = clean_text(value, max_len=20, required=False, label='کد دانش‌آموزی',
                           collapse=False, allow_newline=False)
    if err:
        return '', err
    if text and not STUDENT_CODE_RE.match(text):
        return '', 'کد دانش‌آموزی فقط می‌تواند شامل حروف، عدد و خط تیره باشد (۳ تا ۲۰ نویسه).'
    return text, None


# ---------------------------- بازگشت امن (ضد Open Redirect) ----------------------------

def safe_redirect_target(value, fallback):
    """فقط مسیرهای داخلی مجازند: باید با / شروع شود، // نباشد و اسکیم نداشته باشد."""
    v = (value or '').strip()
    if v.startswith('/') and not v.startswith('//') and not re.match(r'^/\s', v):
        if '\\' not in v and '\n' not in v and '\r' not in v:
            return v
    return fallback


# ---------------------------- اعتبارسنجی فایل آپلودی ----------------------------

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
SHEET_EXTS = ('.xlsx', '.xls', '.csv')


def _ext_of(name):
    name = (name or '').lower()
    for ext in IMAGE_EXTS + SHEET_EXTS:
        if name.endswith(ext):
            return ext
    return ''


def validate_image_upload(f, max_mb=5):
    """تصویر آپلودی: پسوند مجاز + سقف حجم + باز شدن واقعی با Pillow (جلوگیری از فایل جعلی)."""
    if f is None:
        return 'فایلی دریافت نشد.'
    ext = _ext_of(getattr(f, 'name', ''))
    if ext not in IMAGE_EXTS:
        return 'فرمت تصویر مجاز نیست (فقط jpg/png/gif/webp).'
    if getattr(f, 'size', 0) > max_mb * 1024 * 1024:
        return f'حجم تصویر نباید بیشتر از {max_mb} مگابایت باشد.'
    try:
        from PIL import Image
        f.seek(0)
        img = Image.open(f)
        img.verify()
        f.seek(0)
    except Exception:
        return 'فایل ارسال‌شده یک تصویر معتبر نیست.'
    return None


def validate_sheet_upload(f, max_mb=5):
    """فایل Excel/CSV: پسوند + سقف حجم + (برای csv) انکودینگ خوانا."""
    if f is None:
        return 'فایلی دریافت نشد.'
    ext = _ext_of(getattr(f, 'name', ''))
    if ext not in SHEET_EXTS:
        return 'فرمت فایل مجاز نیست (فقط xlsx/xls/csv).'
    if getattr(f, 'size', 0) > max_mb * 1024 * 1024:
        return f'حجم فایل نباید بیشتر از {max_mb} مگابایت باشد.'
    if getattr(f, 'size', 0) == 0:
        return 'فایل خالی است.'
    return None


_FORMULA_LEADERS = ('=', '+', '-', '@', '\t', '\r')


def csv_formula_guard(value):
    """جلوگیری از CSV/Formula Injection هنگام خروجی گرفتن مقادیر کاربرپسند."""
    text = '' if value is None else str(value)
    if text and text[0] in _FORMULA_LEADERS:
        return "'" + text
    return text


# ---------------------------- محدودسازی نرخ درخواست ----------------------------

def rate_limit_hit(request, key, max_hits, window=60):
    """True یعنی «از سقف گذشته». شمارش بر مبنای کاربر (یا آی‌پی اگر ناشناس)."""
    user = getattr(request, 'user', None)
    who = f'u{user.id}' if (user and user.is_authenticated) else f'ip{_client_ip(request)}'
    cache_key = f'rl:{key}:{who}'
    try:
        hits = cache.get(cache_key, 0) + 1
        cache.set(cache_key, hits, window)
    except Exception:
        return False
    return hits > max_hits


def _client_ip(request):
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if fwd:
        first = fwd.split(',')[0].strip()
        if first:
            return first
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def limit(key, max_hits, window=60, message='تعداد درخواست‌ها زیاد است؛ کمی صبر کنید.'):
    """دکوریتور محدودسازی نرخ برای ویوهای POST/AJAX.

    برای درخواست‌های JSON پاسخ 429 JSON و برای بقیه redirect به عقب + پیام messages.
    """
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if rate_limit_hit(request, key, max_hits, window):
                wants_json = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
                              or request.path.startswith(('/student/save', '/student/log'))
                              or request.accepts('application/json'))
                if wants_json:
                    return JsonResponse({'error': message}, status=429)
                messages.error(request, message)
                return redirect_back(request)
            return view(request, *args, **kwargs)
        return wrapper
    return deco


def redirect_back(request, fallback='/', post_key='back'):
    """redirect امن به مسیر بازگشتِ اعلام‌شده در فرم (یا fallback).

    fallback می‌تواند نام URL یا مسیر باشد؛ مقدار کاربر فقط اگر مسیر داخلی
    هم‌میزبان باشد پذیرفته می‌شود (جلوگیری از Open Redirect).
    """
    from django.shortcuts import redirect as _redirect
    from django.urls import reverse, NoReverseMatch

    target = request.POST.get(post_key) or ''
    if target:
        from urllib.parse import urlsplit
        parts = urlsplit(target)
        if parts.netloc and parts.netloc != request.get_host():
            target = ''                      # مقصد بیرونی → رد
        elif parts.netloc:
            target = parts.path + (('?' + parts.query) if parts.query else '')
    target = safe_redirect_target(target, '')
    if not target:
        target = fallback
        if not target.startswith('/'):
            try:
                target = reverse(target)
            except NoReverseMatch:
                target = '/'
    return _redirect(target)


# ---------------------------- پایان نشست‌های یک کاربر ----------------------------

def terminate_user_sessions(user, keep_session_key=None):
    """حذف همهٔ نشست‌های فعال کاربر (مثلاً پس از تغییر رمز). تعداد حذف‌شده‌ها برگردانده می‌شود."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone as tz
    killed = 0
    for s in Session.objects.filter(expire_date__gt=tz.now()):
        if keep_session_key and s.session_key == keep_session_key:
            continue
        try:
            data = s.get_decoded()
        except Exception:
            continue
        if str(data.get('_auth_user_id')) == str(user.id):
            s.delete()
            killed += 1
    try:
        cache.delete(f'user_session_{user.id}')
    except Exception:
        pass
    return killed
