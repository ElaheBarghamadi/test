from pathlib import Path
import os
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# 🔐 SECRET KEY (برای production بهتره از ENV بخونی)

# ⚠️ حالت توسعه / تولید
# اگر متغیر محیطی DEBUG تنظیم نشده باشد: اجرای با `runserver` یعنی توسعه،
# و غیر از آن (gunicorn و…) یعنی تولید — تا روی دستگاه محلی فقط با
# `python manage.py runserver` همه‌چیز بدون تنظیمات اضافه درست کار کند.
import sys


def _env_flag(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


_RUNNING_DEV_SERVER = any(a.startswith('runserver') for a in sys.argv[1:])
DEBUG = _env_flag('DEBUG', _RUNNING_DEV_SERVER)
TESTING = 'test' in sys.argv

# 🔐 SECRET KEY: در تولید حتماً باید از متغیر محیطی خوانده شود
SECRET_KEY = os.getenv('SECRET_KEY', '').strip()
if not SECRET_KEY:
    # دستورات manage.py (migrate، ساخت کاربر و…) بدون کلید هم اجرا شوند؛
    # ولی سرور تولید (gunicorn/wsgi) بدون SECRET_KEY بالا نمی‌آید.
    _SERVING = os.getenv('EXAM_SYSTEM_SERVING') == '1'   # در wsgi.py/asgi.py تنظیم می‌شود
    if DEBUG or TESTING or not _SERVING:
        SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('در حالت تولید متغیر محیطی SECRET_KEY باید تنظیم شود.')

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


if not DEBUG and not TESTING:
    # فقط در حالت تولید: اجبار HTTPS و کوکی‌های امن
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

ALLOWED_HOSTS = ['*']
# برای فرم‌ها پشت HTTPS/پروکسی (مثلاً https://example.com)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
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
    'exam_system.middleware.SecurityHeadersMiddleware',
    'exam_system.middleware.BrandedNotFoundMiddleware',
]

if not DEBUG and not TESTING:
    # سرویس فایل‌های استاتیک با WhiteNoise فقط در تولید؛
    # در توسعه خودِ django.contrib.staticfiles بدون هشدار missing-dir سرو می‌کند.
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')

MIDDLEWARE += [
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
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

# 🗄 DATABASE (Render PostgreSQL ready)
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    )
}

# 🔒 Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# 👤 Custom user
AUTH_USER_MODEL = 'accounts.User'

# 🌍 Localization
LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

# 📦 Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

if not DEBUG and not TESTING:
    # فقط در تولید: فشرده‌سازی + هش‌زدن نام فایل‌ها (نیازمند collectstatic)
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# 📸 Media (for exam images)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# 🔑 Default auto field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 🌐 CORS — فقط میزبان‌های مجاز (پیش‌فرض: هیچ‌کس؛ متغیر محیطی CORS_ALLOWED_ORIGINS)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]
CORS_ALLOW_CREDENTIALS = False

# ⚙️ Session
SESSION_CACHE_ALIAS = 'default'

# 🚨 Custom error handlers
handler400 = 'accounts.views.bad_request'
handler403 = 'accounts.views.permission_denied'
handler404 = 'accounts.views.page_not_found'
handler500 = 'accounts.views.server_error'