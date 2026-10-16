import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


# =====================================================================
# 🔧 خواندن تنظیمات از محیط
# ---------------------------------------------------------------------
# مقدارها از متغیرهای محیطی خوانده می‌شوند تا هیچ رازی داخل مخزن نماند.
# برای ساخت کلید جدید:  python -c "import secrets;print(secrets.token_urlsafe(50))"
# =====================================================================
def _env_bool(name, default=False):
    """متغیر بولی محیطی؛ اگر تنظیم نشده باشد مقدار default برگردانده می‌شود."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=None):
    """فهرست جداشده با کاما از متغیر محیطی."""
    raw = os.environ.get(name, '').strip()
    if not raw:
        return list(default or [])
    return [part.strip() for part in raw.split(',') if part.strip()]


# ⚠️ حالت توسعه / تولید
# اجرای `runserver` یعنی توسعه؛ `manage.py test` یعنی تست؛ gunicorn/uWSGI یعنی تولید.
# با DJANGO_DEBUG یا DJANGO_ENV می‌توانید صریحاً override کنید.
_RUNNING_DEV_SERVER = any(a.startswith('runserver') for a in sys.argv[1:])
TESTING = 'test' in sys.argv or any(a.startswith('test') for a in sys.argv[1:])
_forced_debug = os.environ.get('DJANGO_DEBUG')
if _forced_debug is not None and _forced_debug.strip():
    DEBUG = _env_bool('DJANGO_DEBUG')
else:
    DEBUG = _RUNNING_DEV_SERVER

#: نام فرمانی که فرآیند را راه انداخته — `manage.py` یعنی یک دستور مدیریتی
#: (migrate/check/collectstatic/…) و نه یک وب‌سرورِ در حال سرو.
_LAUNCHER = os.path.basename(sys.argv[0] or '').lower()
_IS_MANAGE_PY = _LAUNCHER == 'manage.py'

_DJANGO_ENV = os.environ.get('DJANGO_ENV', '').strip().lower()
if _DJANGO_ENV in ('prod', 'production'):
    #: صریحاً تولید — حتی برای `manage.py check --deploy`
    IS_PRODUCTION = True
elif _DJANGO_ENV in ('dev', 'development', 'test', 'testing'):
    IS_PRODUCTION = False
else:
    # استنتاج: نه runserver، نه تست، و نه یک دستور manage.py →
    # یعنی توسط یک وب‌سرور واقعی (gunicorn/uWSGI/WSGI) سرو می‌شویم.
    IS_PRODUCTION = (not DEBUG) and (not TESTING) and (not _IS_MANAGE_PY)


# =====================================================================
# 🔐 SECRET_KEY
# ---------------------------------------------------------------------
# در تولید «الزامی» است و در صورت نبود، برنامه عمداً بالا نمی‌آید (fail-fast).
# کلید قبلی که به‌عنوان fallback داخل مخزن عمومی بود دیگر استفاده نمی‌شود و
# باید rotate شود؛ کلید زیر فقط برای توسعه است و در تولید پذیرفته نیست.
# =====================================================================
_DEV_ONLY_SECRET_KEY = 'dev-only-j_WLU8ZG7ByDdrnwce_Q2fsXkQR7pe_y8X1O5vU1SSoeP8WKvHj5Q'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '').strip()
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY تنظیم نشده است. در حالت تولید این متغیر محیطی الزامی است.\n'
            'ساخت کلید تازه:  python -c "import secrets;print(secrets.token_urlsafe(50))"\n'
            'سپس آن را در محیط استقرار (مثلاً Render → Environment) قرار دهید.')
    SECRET_KEY = _DEV_ONLY_SECRET_KEY


# 🔒 کوکی‌ها و نشست‌ها
SESSION_COOKIE_HTTPONLY = True          # جاوااسکریپت به کوکی نشست دسترسی ندارد
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False            # اسکریپت‌های سامانه توکن CSRF را می‌خوانند
SESSION_COOKIE_AGE = 60 * 60 * 12       # ۱۲ ساعت
SESSION_SAVE_EVERY_REQUEST = True       # انقضای لغزنده برای خروج خودکار در عدم فعالیت
X_FRAME_OPTIONS = 'DENY'                # جلوگیری از قرارگیری در iframe (کلیک‌ربایی)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'


# =====================================================================
# 🔒 HTTPS — پیش‌فرض در تولید «امن» است
# ---------------------------------------------------------------------
# پیش‌تر HTTPS_ONLY به‌صورت سخت‌کد False بود، پس کوکی‌های Secure و HSTS و
# ریدایرکت HTTPS در هیچ استقرار production فعال نمی‌شد (هشدارهای W004/W008/
# W012/W016 در `manage.py check --deploy`).
# اکنون: در تولید به‌صورت پیش‌فرض روشن است؛ اگر سایت واقعاً روی http سرو
# می‌شود با DJANGO_HTTPS_ONLY=0 خاموشش کنید.
# =====================================================================
HTTPS_ONLY = _env_bool('DJANGO_HTTPS_ONLY', default=IS_PRODUCTION)

# فقط پشت reverse proxy معتبر (Render/Nginx) معنا دارد؛ در توسعه تنظیم نمی‌شود.
# ⚠️ این هدر تنها زمانی قابل اعتماد است که proxy ورودی، هدر جعلی مشتری را پاک کند.
if IS_PRODUCTION:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if HTTPS_ONLY and IS_PRODUCTION:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', 60 * 60 * 24 * 365))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('DJANGO_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = _env_bool('DJANGO_HSTS_PRELOAD', default=False)


# =====================================================================
# 🌐 ALLOWED_HOSTS — دیگر wildcard در تولید پذیرفته نمی‌شود
# ---------------------------------------------------------------------
# `['*']` دفاع جنگو در برابر Host-header injection را از کار می‌انداخت.
# دامنه‌های خود را با DJANGO_ALLOWED_HOSTS بدهید:
#   DJANGO_ALLOWED_HOSTS=example.com,www.example.com
# (نقطهٔ آغازین یعنی همهٔ زیردامنه‌ها:  .onrender.com)
# =====================================================================
_configured_hosts = _env_list('DJANGO_ALLOWED_HOSTS')
if _configured_hosts:
    ALLOWED_HOSTS = _configured_hosts
elif IS_PRODUCTION:
    # fallback محافظه‌کارانه به‌جای wildcard — دامنهٔ خود را صریح تنظیم کنید
    ALLOWED_HOSTS = ['.onrender.com', 'localhost', '127.0.0.1']
else:
    ALLOWED_HOSTS = ['*']

# برای فرم‌ها پشت HTTPS/پروکسی — با DJANGO_CSRF_TRUSTED_ORIGINS قابل افزودن است
CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[
    'https://*.onrender.com',
    'https://*.e2b.app',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
])

# 🧩 Apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # third party
    'rest_framework',
    'corsheaders',

    # your apps
    'accounts',
    'exams',
    'teacher_panel',
    'student_panel',
    'admin_panel',
]

# 🧱 Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise همیشه فعال است: CSS/فونت‌ها در هر حالتی (runserver یا gunicorn) سرو می‌شوند
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'exam_system.middleware.SecurityHeadersMiddleware',
    'exam_system.middleware.BrandedNotFoundMiddleware',
]

MIDDLEWARE += [
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # آمار بازدید پس از شناسایی کاربر ثبت می‌شود.
    'admin_panel.analytics_middleware.SiteAnalyticsMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'exam_system.urls'

# 🎨 Templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'builtins': ['student_panel.templatetags.jalali_tags'],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'exams.context_processors.announcements',
            ],
        },
    },
]

WSGI_APPLICATION = 'exam_system.wsgi.application'

# 🗄 DATABASE
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# کش مشترک برای rate-limit در چند worker. در توسعه، LocMem کافی است؛
# روی سرور REDIS_URL را تنظیم کنید تا شمارنده‌ها بین workerها مشترک باشند.
_REDIS_URL = os.environ.get('REDIS_URL', '').strip()
CACHES = {
    'default': ({
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': _REDIS_URL,
        'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
    } if _REDIS_URL else {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'exam-system-dev-cache',
    })
}
# فقط اگر برنامه پشت reverse proxy مطمئن است این مقدار را برابر تعداد proxyها بگذارید.
TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', '0'))

# 🔒 Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 👤 Custom user
AUTH_USER_MODEL = 'accounts.User'

# 🔑 مسیر ورود — بدون این تنظیم، جنگو از پیش‌فرض `/accounts/login/` استفاده می‌کند
# که در این پروژه وجود ندارد؛ در نتیجه کاربر ناشناس از هر صفحهٔ محافظت‌شده
# به یک صفحهٔ ۴۰۴ پرت می‌شد.
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = 'home'

# 🌍 Localization
LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

# 📦 Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_ROOT.mkdir(parents=True, exist_ok=True)  # prevents WhiteNoise 'No directory' warning

# Django 5.2 فقط STORAGES را می‌شناسد (STATICFILES_STORAGE حذف شده است).
# ذخیره‌ساز بدون manifest: اگر collectstatic اجرا نشده باشد هم صفحه‌ها خطا نمی‌دهند.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
# فایل‌ها مستقیم از پوشهٔ static/ هم سرو می‌شوند؛ اجرای collectstatic اختیاری است
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_MAX_AGE = 60 * 60 * 24 * 7

# 📸 Media (for exam images)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 🔑 Default auto field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🌐 CORS — فقط میزبان‌های مجاز (پیش‌فرض: هیچ‌کس؛ متغیر محیطی CORS_ALLOWED_ORIGINS)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
CORS_ALLOW_CREDENTIALS = False

# ⚙️ Session
SESSION_CACHE_ALIAS = 'default'

# 🚨 Custom error handlers
handler400 = 'accounts.views.bad_request'
handler403 = 'accounts.views.permission_denied'
handler404 = 'accounts.views.page_not_found'
handler500 = 'accounts.views.server_error'
CSRF_FAILURE_VIEW = 'accounts.views.csrf_failure'