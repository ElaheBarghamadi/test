# سامانه آزمون غیرحضوری

سامانه مدیریت و برگزاری آزمون آنلاین (معلم / دانش‌آموز / مدیر) با جنگو.

---

## 🚀 اجرای پروژه روی دستگاه خودتان (حالت توسعه)

### پیش‌نیاز
- پایتون **3.11 یا جدیدتر** ([python.org](https://www.python.org/downloads/))
- در ویندوز هنگام نصب، تیک **Add Python to PATH** را بزنید.

### ۱) دریافت کد
```bash
git clone https://github.com/ElaheBarghamadi/test.git
cd test
```

### ۲) ساخت محیط مجازی و نصب وابستگی‌ها
**ویندوز (CMD یا PowerShell):**
```bat
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
**لینوکس / مک:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### ۳) ساخت دیتابیس
```bash
python manage.py migrate
```

### ۴) داده نمونه (اختیاری ولی توصیه‌شده)
```bash
python manage.py seed_demo
```
این دستور کاربرها و دو آزمون کامل (با همه انواع سوال و تصویر) می‌سازد:

| نقش | نام کاربری | رمز |
|---|---|---|
| مدیر | `admin_t` | `test12345` |
| معلم | `teacher_t` | `test12345` |
| دانش‌آموز | `student_t1` (و `student_t2`, `student_t3`) | `test12345` |

### ۴.۵) کاربران پیش‌فرض (خودکار)
با هر بار اجرای `runserver` (یا دستی با `python create_default_users.py` / `python manage.py ensure_default_users`)
این سه کاربر **اگر وجود نداشته باشند** ساخته می‌شوند (رمز = نام کاربری):

| نقش | نام کاربری | رمز |
|---|---|---|
| مدیر اصلی | `admin` | `admin` |
| معلم | `teacher` | `teacher` |
| دانش‌آموز | `student` | `student` |

> ⚠️ در سرور واقعی حتماً رمز این کاربران را عوض کنید.

### ۴.۶) بانک سوال نمونه (پوشه‌بندی‌شده)
```bash
python manage.py seed_question_bank                # برای معلم teacher
python manage.py seed_question_bank --teacher ali  # برای معلم دیگر
python manage.py seed_question_bank --all          # برای همهٔ معلم‌ها
python manage.py seed_question_bank --reset        # پاک‌کردن بانک معلم و ساخت دوباره
```
حدود ۹۴ سوال از همهٔ انواع در ساختار «پایه › درس › فصل». معلم می‌تواند از دکمهٔ
«✨ بارگذاری بانک نمونه» در صفحهٔ بانک سوال هم همین کار را انجام دهد. اجرای دوباره سوال تکراری نمی‌سازد.

### ۵) اجرای سرور
```bash
python manage.py runserver
```
سپس مرورگر: <http://127.0.0.1:8000/>

> 💡 حالت توسعه به‌صورت خودکار فعال می‌شود: چون با `runserver` اجرا کرده‌اید،
> `DEBUG=True` در نظر گرفته می‌شود (بدون نیاز به تنظیم متغیر محیطی).
> فایل‌های استاتیک و رسانه همین‌طور سرو می‌شوند و ریدایرکت HTTPS اتفاق نمی‌افتد.

---

## 🔧 متغیرهای محیطی (اختیاری)

| متغیر | معنی | پیش‌فرض |
|---|---|---|
| `DEBUG` | `True`/`False` — حالت توسعه یا تولید | اگر تنظیم نشده: با `runserver` = توسعه، وگرنه = تولید |
| `SECRET_KEY` | کلید امنیتی جنگو | در توسعه مقدار موقت؛ **در تولید اجباری** (بدون آن gunicorn بالا نمی‌آید) |
| `ALLOWED_HOSTS` | دامنه‌های مجاز در تولید، جدا با ویرگول | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | مثلاً `https://your-domain.com` | خالی |
| `DATABASE_URL` | آدرس دیتابیس (مثلاً postgres) | sqlite فایل `db.sqlite3` |
| `CORS_ALLOWED_ORIGINS` | فهرست میزبان‌های مجاز CORS، جدا شده با ویرگول | خالی (هیچ میزبانی مجاز نیست) |

مثال ویندوز:
```bat
set DEBUG=True
set SECRET_KEY=my-super-secret-key
python manage.py runserver
```

---

## 🌐 اجرای تولید (Production)

```bash
export DEBUG=False
export SECRET_KEY='یک-کلید-طولانی-و-تصادفی'
export DATABASE_URL='postgres://USER:PASS@HOST/DB'   # یا خالی برای sqlite
export ALLOWED_HOSTS='your-domain.com'
export CSRF_TRUSTED_ORIGINS='https://your-domain.com'
export CORS_ALLOWED_ORIGINS='https://your-domain.com'

python manage.py migrate
python manage.py collectstatic --noinput
gunicorn exam_system.wsgi:application --bind 0.0.0.0:8000
```
در حالت تولید: کوکی‌ها `Secure` می‌شوند، ریدایرکت HTTPS و HSTS فعال است و
فایل‌های استاتیک با WhiteNoise سرو می‌شوند (پوشه `staticfiles/` توسط `collectstatic` ساخته می‌شود).
فایل‌های آپلودشده (`media/`) فقط از مسیر محافظت‌شده `/media/` و با احراز دسترسی سرو می‌شوند.

---

## 🧪 تست‌ها

```bash
python manage.py test          # تست‌های واحد (کنترل دسترسی، امنیت، جریان‌ها)
```

---

## ❓ خطاهای رایج

| خطا | علت و راه‌حل |
|---|---|
| `You're accessing the development server over HTTPS...` + ریدایرکت 301 | سرور توسعه با `DEBUG=False` اجرا شده. با `runserver` این حالت خودکار رفع می‌شود؛ در غیر این صورت `set DEBUG=True` بزنید. |
| `UserWarning: No directory at: .../staticfiles/` | فقط در حالت تولید معنا دارد؛ `collectstatic --noinput` اجرا کنید. در توسعه این هشدار ظاهر نمی‌شود. |
| `No module named 'django'` | محیط مجازی فعال نیست: `.venv\Scripts\activate` |
| فونت فارسی نمایش داده نمی‌شود | در تولید ابتدا `collectstatic` لازم است. |
