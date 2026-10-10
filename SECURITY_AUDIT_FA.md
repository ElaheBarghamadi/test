# گزارش بازبینی فنی و امنیتی سامانه آزمون

تاریخ بررسی: ۱۴۰۵/۰۷/۱۸ (2026-10-10)

## خلاصه اجرایی

پروژه از نظر کنترل مالکیت اشیا، CSRF middleware، اعتبارسنجی فایل تصویر، محافظت از media، محدودسازی ورود، ORM و تست‌ها وضعیت نسبتاً خوبی دارد؛ اما در پیکربندی production و چند endpoint تغییر‌دهنده وضعیت، ایرادهای امنیتی مهم وجود دارد.

**نتیجه کلی:** برای استقرار عمومی در وضعیت فعلی توصیه نمی‌شود؛ موارد بحرانی و زیاد باید ابتدا اصلاح شوند.

- بحرانی: 1 مورد
- زیاد: 4 مورد
- متوسط: 6 مورد
- کم/کیفی: 4 مورد

---

## یافته‌های امنیتی

### 1) بحرانی — کلید ثابت و عمومی Django (`SECRET_KEY`)

**محل:** `exam_system/settings.py:17-19`

کلید واقعی به‌عنوان fallback داخل مخزن عمومی قرار دارد. در نتیجه هر deployment که متغیر `DJANGO_SECRET_KEY` را تنظیم نکند از کلیدی استفاده می‌کند که مهاجم می‌داند. این کلید برای امضاهای Django و همچنین لینک‌های هش‌شده آزمون استفاده می‌شود.

**اثر:** تضعیف/جعل داده‌های امضاشده، افشای ساختار لینک آزمون، و افزایش شدید ریسک در هر بخشی که به signing متکی است. حتی اگر session فعلی دیتابیسی باشد، این کلید نباید عمومی یا اختیاری باشد.

**اصلاح:**

```python
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']
```

در production در صورت نبود متغیر، برنامه باید fail-fast شود. کلید فعلی را فوراً rotate کنید. برای dev یک فایل `.env` خارج از Git یا کلید dev صریح و غیرقابل استفاده در production در نظر بگیرید.

---

### 2) زیاد — عملیات مخرب با GET و امکان CSRF

چند view داده را بدون محدودکردن method تغییر می‌دهند. `CsrfViewMiddleware` درخواست GET را بررسی نمی‌کند؛ بنابراین لینک یا تصویر خارجی می‌تواند مرورگر مدیر/معلم لاگین‌شده را وادار به اجرای عملیات کند.

**موارد قطعی:**

- حذف کاربر: `admin_panel/views.py:604-621`
- فعال/غیرفعال‌کردن آزمون توسط مدیر: `admin_panel/views.py:1171-1181`
- حذف آزمون توسط مدیر: `admin_panel/views.py:1184-1193`
- حذف آزمون توسط معلم: `teacher_panel/views.py:472-484`
- فعال/غیرفعال‌کردن آزمون توسط معلم: `teacher_panel/views.py:487-501`
- ثبت نهایی آزمون دانش‌آموز با GET: `student_panel/views.py:1040-1091`

**اثر:** حذف کاربر/آزمون، تغییر وضعیت آزمون، یا ثبت ناخواسته آزمون قربانی.

**اصلاح:** روی تمام این viewها `@require_POST` یا `@require_http_methods(['POST'])` بگذارید و UI را فقط با فرم POST دارای `{% csrf_token %}` پیاده کنید. `submit_exam` در GET باید فقط صفحه تأیید نشان دهد یا 405 برگرداند و هرگز status را تغییر ندهد.

---

### 3) زیاد — HTTPS در حالت پیش‌فرض خاموش است

**محل:** `exam_system/settings.py:33-42`

`HTTPS_ONLY = False` است؛ بنابراین `SESSION_COOKIE_SECURE`، `CSRF_COOKIE_SECURE`، redirect اجباری SSL و HSTS فعال نیستند. اجرای `manage.py check --deploy` نیز چهار هشدار امنیتی W004، W008، W012 و W016 گزارش کرد.

**اثر:** در deployment اشتباه یا شبکه ناامن، سرقت session/CSRF cookie و downgrade به HTTP ممکن است.

**اصلاح:** تنظیمات production را از environment بگیرید و پیش‌فرض production را امن قرار دهید. `SECURE_SSL_REDIRECT=True`، کوکی‌های Secure و HSTS را پس از اطمینان از HTTPS صحیح فعال کنید. مقدار `SECURE_PROXY_SSL_HEADER` فقط زمانی قابل اعتماد است که proxy ورودی header جعلی را پاک‌سازی کند.

---

### 4) زیاد — `ALLOWED_HOSTS = ['*']`

**محل:** `exam_system/settings.py:44`

همه Hostها پذیرفته می‌شوند. این کار دفاع Django در برابر Host-header injection را تضعیف می‌کند و می‌تواند روی ساخت URL مطلق، لینک‌های تولیدشده و منطق هم‌میزبان اثر بگذارد.

**اصلاح:** دامنه‌ها را از متغیر محیطی با allowlist صریح بخوانید؛ مثلاً `example.com,www.example.com`، و wildcard را فقط در dev مجاز کنید.

---

### 5) زیاد — بکاپ کامل داده با درخواست GET

**محل:** `admin_panel/views.py:1465-1510`

endpoint بکاپ با GET اجرا می‌شود و هر بار `dumpdata` کامل تولید می‌کند. بکاپ شامل داده‌های حساس و احتمالاً hash رمزهاست. چون GET تحت CSRF check نیست، مهاجم می‌تواند با درخواست‌های cross-site باعث تولید مکرر فایل و پرشدن دیسک/مصرف CPU شود.

**اصلاح:** فقط POST + CSRF، rate limit، audit log، محدودیت تعداد/حجم/عمر بکاپ، مجوز صریح‌تر و ترجیحاً job غیرهمزمان. خطای خام subprocess نیز نباید به کاربر بازگردد.

---

### 6) متوسط — اعتماد مستقیم به `X-Forwarded-For`

**محل‌ها:** `accounts/views.py:18-23`، `core/security.py:217-223` و منطق‌های مشابه

اولین مقدار `X-Forwarded-For` بدون بررسی proxy مورد اعتماد، به‌عنوان IP واقعی استفاده می‌شود.

**اثر:** دورزدن rate-limit مبتنی بر IP، آلوده‌کردن لاگ‌های امنیتی و گمراه‌کردن تشخیص تغییر IP؛ در صورتی که reverse proxy header ورودی را بازنویسی نکند.

**اصلاح:** IP را فقط از proxy مورد اعتماد دریافت کنید؛ در غیر این صورت `REMOTE_ADDR`. تنظیم proxy باید header کاربر را حذف و مقدار canonical بسازد. از کتابخانه/منطق trusted-proxy استفاده شود.

---

### 7) متوسط — rate limiter اتمیک و fail-closed نیست

**محل:** `core/security.py:204-214`

الگوی `get + 1` سپس `set` اتمیک نیست و در درخواست همزمان شمارش از دست می‌رود. با هر درخواست TTL دوباره از ابتدا تنظیم می‌شود. در خطای cache نیز تابع `False` برمی‌گرداند و محدودسازی کاملاً باز می‌شود.

**اثر:** دورزدن محدودیت در concurrency بالا و حذف دفاع هنگام اختلال cache.

**اصلاح:** Redis `INCR` اتمیک + `EXPIRE` فقط در اولین increment، یا throttle استاندارد و تست‌شده. برای login تصمیم fail-open/fail-closed باید آگاهانه و همراه monitoring باشد.

---

### 8) متوسط — CSP با `unsafe-inline` برای script

**محل:** `exam_system/middleware.py` در `SecurityHeadersMiddleware`

`script-src 'self' 'unsafe-inline'` بخش مهمی از حفاظت CSP در برابر XSS را خنثی می‌کند.

**اصلاح:** JavaScriptهای inline را به فایل استاتیک منتقل کنید یا nonce تصادفی per-response به کار ببرید و `unsafe-inline` را از `script-src` حذف کنید. ابتدا با `Content-Security-Policy-Report-Only` تست شود.

---

### 9) متوسط — بازگرداندن متن exception داخلی به کلاینت

**نمونه‌ها:** `student_panel/views.py:894-895` و endpointهای متعدد با `{'error': str(e)}`؛ همچنین `admin_panel/views.py:1500`.

**اثر:** افشای نام فیلد، مسیر، خطای DB یا جزئیات داخلی که برای مهاجم مفید است.

**اصلاح:** پیام عمومی با شناسه رخداد برگردانید؛ جزئیات فقط server-side با logger و traceback ثبت شود.

---

### 10) متوسط — چند endpoint فاقد `@login_required`

**محل‌ها:**

- `teacher_panel/views.py:1278` — `duplicate_exam`
- `teacher_panel/views.py:1299` — `export_results_csv`
- `teacher_panel/views.py:1378` — `question_bank`

کنترل‌های داخل تابع تا حدی مالکیت/نقش را بررسی می‌کنند، ولی برای کاربر ناشناس احتمال خطای 500 و رفتار ناهماهنگ وجود دارد. decorator دفاع صریح و یکنواخت ایجاد می‌کند.

**اصلاح:** `@login_required` اضافه شود؛ برای duplicate همچنین `@require_POST`.

---

### 11) متوسط — سیاست رمز سفارشی به‌جای validatorهای Django

`password_policy` فقط طول ۸، وجود حرف/عدد و نبود فاصله را بررسی می‌کند. این مسیرها لزوماً `validate_password()` خود Django را اجرا نمی‌کنند؛ بنابراین similarity/common-password validators ممکن است در ساخت/بازنشانی مدیر اعمال نشوند.

**اصلاح:** از `django.contrib.auth.password_validation.validate_password(password, user)` به‌عنوان مرجع اصلی استفاده کنید و خطاهای فارسی مناسب نمایش دهید. حداقل طول ۱۲ برای رمزهای محلی پیشنهاد می‌شود؛ MFA برای مدیران مهم‌تر است.

---

## ایرادهای فنی و کیفی

### 12) نبود تنظیم database تولید

تنظیمات فقط SQLite دارد (`exam_system/settings.py`). برای آزمون همزمان و چند worker، SQLite خطر lock و افت پایداری دارد؛ با وجود `psycopg2` هیچ تنظیم PostgreSQL دیده نمی‌شود.

### 13) تشخیص DEBUG بر اساس نام command

`DEBUG` با وجود `runserver` در argv خودکار True می‌شود. این رفتار ضمنی خطر خطای عملیاتی دارد. بهتر است فقط از environment و پیش‌فرض False استفاده شود.

### 14) وابستگی‌های غیرضروری/سطح حمله بیشتر

`djangorestframework`، `django-cors-headers`، `requests`، `django-redis` و چند بسته سنگین نصب شده‌اند، در حالی که میزان استفاده باید بازبینی شود. هر وابستگی غیرضروری سطح حمله و هزینه patch را بالا می‌برد.

### 15) چندین عملیات حساس بدون محدودیت نرخ

ساخت/ویرایش/حذف کاربران، export و backup محدودیت نرخ مستقل ندارند. مجوز نقش وجود دارد، ولی account takeover مدیر می‌تواند اثر بزرگ‌تری ایجاد کند. برای عملیات حساس re-authentication، MFA و rate-limit مناسب است.

---

## نقاط مثبت مشاهده‌شده

- استفاده از ORM و ندیدن SQL خام یا `eval/exec` روی ورودی کاربر.
- CSRF middleware فعال است.
- logout فقط POST است.
- کنترل مالکیت آزمون در اکثر viewهای معلم.
- کنترل عضویت دانش‌آموز در آزمون برای ذخیره پاسخ.
- سرو محافظت‌شده فایل‌های media با جلوگیری از path traversal.
- اعتبارسنجی تصویر با Pillow، محدودیت حجم و نام تصادفی پاسخ تصویری.
- هدرهای `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` و CSP پایه.
- محافظت login در برابر brute force و ثبت رخدادهای امنیتی.
- جلوگیری از CSV formula injection در utility مربوطه (باید اطمینان حاصل شود در تمام exportها اعمال می‌شود).
- محدودیت‌های دیتابیسی برای مدت/زمان آزمون و نمره سؤال.
- `.gitignore` مناسب برای DB، media، backup و `.env`؛ فایل DB یا credential اضافه‌شده به Git مشاهده نشد.

---

## نتایج تست و ابزار

- `python manage.py check --deploy`: چهار هشدار مرتبط با HTTPS/HSTS/Secure Cookie.
- `python manage.py test`: **225 تست، همگی موفق**.
- وجود تست خوب است، اما تست‌های فعلی موارد GET مخرب/CSRF و الزامات production را پوشش نداده‌اند.
- هنگام نصب در محیط بررسی، conflict محیطی NumPy با بسته‌های از قبل نصب‌شده مشاهده شد؛ این الزاماً ایراد خود پروژه نیست، ولی استفاده از محیط مجازی/کانتینر و lockfile توصیه می‌شود.

---

## ترتیب پیشنهادی اصلاح

1. rotate کردن `SECRET_KEY` و اجباری‌کردن environment secret.
2. تبدیل تمام عملیات تغییر‌دهنده به POST-only؛ به‌خصوص حذف‌ها، toggleها و submit آزمون.
3. امن‌سازی production: HTTPS، Secure cookies، HSTS و `ALLOWED_HOSTS` محدود.
4. POST-only و rate-limit کردن backup با retention policy.
5. اصلاح trusted proxy/IP و rate limiter اتمیک.
6. افزودن `login_required`های جاافتاده و حذف نمایش exception خام.
7. CSP nonce-based، اعتبارسنجی رمز استاندارد Django و افزودن MFA مدیر.
8. افزودن تست regression برای همه موارد بالا.
