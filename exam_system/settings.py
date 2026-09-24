from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent

# ⚙️ همهٔ تنظیمات مستقیماً در همین فایل است (فعلاً فایل .env نداریم).
# برای ساخت کلید جدید: python -c "import secrets;print(secrets.token_urlsafe(50))"

# ⚠️ حالت توسعه / تولید: اجرای `runserver` یعنی توسعه؛ gunicorn و… یعنی تولید.
# برای اجبار، مقدار DEBUG را مستقیم True/False بگذارید.
_RUNNING_DEV_SERVER = any(a.startswith('runserver') for a in sys.argv[1:])
DEBUG = _RUNNING_DEV_SERVER
TESTING = 'test' in sys.argv

# 🔐 کلید امنیتی
SECRET_KEY = 'k7Qm2vX9pR4tLw8zN3bH6yJc1fD5sG0aE-uVxZqWiOoPlKjMnB_rTyUe4hS8dC2g'

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


# 🔒 HTTPS: فقط وقتی سایت واقعاً روی https است True کنید.
# اگر روی http باشد و True باشد، کوکی ورود/CSRF ارسال نمی‌شود و ورود کار نمی‌کند.
HTTPS_ONLY = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if HTTPS_ONLY and not DEBUG and not TESTING:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

ALLOWED_HOSTS = ['*']
# برای فرم‌ها پشت HTTPS/پروکسی (مثلاً https://example.com)
CSRF_TRUSTED_ORIGINS = ['https://*.onrender.com', 'https://*.e2b.app', 'http://localhost:8000', 'http://127.0.0.1:8000']
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