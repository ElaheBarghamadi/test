from django.db import models

# Create your models here.
# exams/models.py

from django.db import models
from django.core.cache import cache


class SystemSetting(models.Model):
    """تنظیمات سیستمی - فقط مدیر قابل دسترسی"""

    SETTING_TYPES = [
        ('general', 'تنظیمات عمومی'),
        ('report_card', 'تنظیمات کارنامه'),
        ('security', 'تنظیمات امنیتی'),
        ('notification', 'تنظیمات اعلان‌ها'),
    ]

    key = models.CharField(max_length=100, unique=True, verbose_name='کلید')
    value = models.TextField(blank=True, null=True, verbose_name='مقدار')
    setting_type = models.CharField(max_length=50, choices=SETTING_TYPES, default='general', verbose_name='نوع تنظیمات')
    description = models.TextField(blank=True, null=True, verbose_name='توضیحات')
    is_active = models.BooleanField(default=True, verbose_name='فعال')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تنظیمات سیستم'
        verbose_name_plural = 'تنظیمات سیستم'
        ordering = ['setting_type', 'key']

    def __str__(self):
        return f"{self.key} = {self.value[:50] if self.value else '---'}"

    @classmethod
    def get_setting(cls, key, default=None):
        """دریافت مقدار یک تنظیم با کش خودکار"""
        cache_key = f'system_setting_{key}'
        value = cache.get(cache_key)

        if value is None:
            try:
                setting = cls.objects.get(key=key, is_active=True)
                value = setting.value
                cache.set(cache_key, value, 3600)  # کش برای 1 ساعت
            except cls.DoesNotExist:
                value = default
                cache.set(cache_key, value, 3600)

        # تبدیل string 'true'/'false' به boolean
        if value == 'true':
            return True
        if value == 'false':
            return False

        return value

    @classmethod
    def set_setting(cls, key, value, setting_type='general', description=''):
        """تنظیم مقدار یک تنظیم و پاک کردن کش"""
        setting, created = cls.objects.update_or_create(
            key=key,
            defaults={
                'value': str(value),
                'setting_type': setting_type,
                'description': description,
                'is_active': True
            }
        )
        # پاک کردن کش
        cache_key = f'system_setting_{key}'
        cache.delete(cache_key)
        return setting

# ============================================================================
#  رویدادهای امنیتی + تجزیه User-Agent  (برای صفحهٔ «جزئیات کاربر»)
# ============================================================================
import re
from django.conf import settings as dj_settings


class SecurityEvent(models.Model):
    """رویداد امنیتی کاربر: ورود، خروج، تلاش ناموفق، پایان نشست، تغییر رمز…

    این جدول توسط accounts/views و admin_panel/views پر می‌شود و در صفحهٔ
    جزئیات کاربر به مدیر نشان داده می‌شود.
    """

    EVENT_TYPES = [
        ('login', 'ورود موفق'),
        ('login_failed', 'ورود ناموفق'),
        ('login_locked', 'قفل شدن حساب'),
        ('logout', 'خروج از حساب'),
        ('session_expired', 'انقضای نشست'),
        ('session_revoked', 'پایان نشست توسط مدیر'),
        ('password_changed', 'تغییر رمز عبور'),
        ('profile_updated', 'ویرایش مشخصات توسط مدیر'),
        ('account_created', 'ساخت حساب'),
        ('account_deleted', 'حذف حساب'),
        ('cheat_detected', 'رفتار مشکوک در آزمون'),
        ('ip_changed', 'تغییر آی‌پی در نشست آزمون'),
    ]

    SEVERITY_CHOICES = [
        ('info', 'معمولی'),
        ('notice', 'توجه'),
        ('warning', 'هشدار'),
        ('critical', 'بحرانی'),
    ]

    user = models.ForeignKey(dj_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='security_events', null=True, blank=True,
                             verbose_name='کاربر')
    username_snapshot = models.CharField(max_length=150, blank=True, default='',
                                         verbose_name='نام کاربری (برای موارد حذف کاربر)')
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES, db_index=True)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='info')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='آی‌پی')
    user_agent = models.TextField(blank=True, default='', verbose_name='User-Agent خام')
    browser = models.CharField(max_length=40, blank=True, default='')
    os = models.CharField(max_length=40, blank=True, default='')
    device = models.CharField(max_length=20, blank=True, default='')
    session_key = models.CharField(max_length=64, blank=True, default='')
    detail = models.TextField(blank=True, default='', verbose_name='توضیح')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
        ]
        verbose_name = 'رویداد امنیتی'
        verbose_name_plural = 'رویدادهای امنیتی'

    def __str__(self):
        who = self.username_snapshot or (self.user.username if self.user_id else 'نامشخص')
        return f'{who} — {self.get_event_type_display()}'

    # ---- میان‌برهای نمایشی ----
    @property
    def device_label(self):
        parts = [p for p in (self.device, self.os, self.browser) if p and p != 'نامشخص']
        return ' · '.join(dict.fromkeys(parts)) or 'دستگاه ناشناس'


def client_ip(request):
    """آی‌پی واقعی کلاینت (با احترام به پروکسی/reverse-proxy)"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        first = forwarded.split(',')[0].strip()
        if first:
            return first
    real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
    if real_ip:
        return real_ip
    return request.META.get('REMOTE_ADDR', '') or None


# ------------------------- تجزیه User-Agent -------------------------
_BROWSER_RULES = [
    (r'edg(?:e|a|ios)?/', 'Edge'),
    (r'opr/|opera', 'Opera'),
    (r'samsungbrowser/', 'Samsung Browser'),
    (r'ucbrowser/', 'UC Browser'),
    (r'firefox/|fxios/', 'Firefox'),
    (r'chrome/|crios/', 'Chrome'),
    (r'safari/(?!.*chrome)', 'Safari'),
]
_OS_RULES = [
    (r'windows nt 10', 'Windows 10/11'),
    (r'windows nt 6\.3', 'Windows 8.1'),
    (r'windows nt 6\.1', 'Windows 7'),
    (r'windows', 'Windows'),
    (r'android[ /]?(\d+)?', 'Android'),
    (r'(iphone|ipad|ipod).*os (\d+)[_.](\d+)', 'iOS'),
    (r'mac os x', 'macOS'),
    (r'ubuntu', 'Ubuntu'),
    (r'debian', 'Debian'),
    (r'fedora', 'Fedora'),
    (r'linux', 'Linux'),
    (r'cros', 'ChromeOS'),
]
_DEVICE_RULES = [
    (r'ipad|tablet|(android(?!.*mobile))|kindle|silk', 'تبلت'),
    (r'iphone|ipod|android.*mobile|windows phone|mobile', 'موبایل'),
    (r'bot|crawl|spider|curl|python-requests|headless', 'ربات/اسکریپت'),
]


def _first(pattern, ua, group=None):
    m = re.search(pattern, ua, re.I)
    if not m:
        return ''
    if group:
        try:
            return m.group(group) or ''
        except Exception:
            return ''
    return m.group(0)


def parse_user_agent(ua):
    """تبدیل رشتهٔ User-Agent به (مرورگر، سیستم‌عامل، نوع دستگاه) — بدون وابستگی بیرونی"""
    ua = (ua or '').strip()
    if not ua:
        return {'browser': 'نامشخص', 'os': 'نامشخص', 'device': 'نامشخص', 'raw': ''}

    browser = ''
    for pattern, name in _BROWSER_RULES:
        if re.search(pattern, ua, re.I):
            version = _first(pattern.rstrip('/') + r'\s*([0-9][0-9.]*)', ua, 1) if pattern.endswith('/') else ''
            if not version:
                m = re.search(r'(?:version|chrome|firefox|edg|opr|samsungbrowser|ucbrowser)[/ ]([0-9][0-9.]*)', ua, re.I)
                version = m.group(1) if m else ''
            browser = f'{name} {version.split(".")[0]}' if version else name
            break
    if not browser:
        m = re.search(r'([A-Za-z][A-Za-z0-9\-+]*)/(\d+)', ua)
        browser = f'{m.group(1).lower()} {m.group(2)}' if m else 'نامشخص'

    os_name = ''
    for pattern, name in _OS_RULES:
        m = re.search(pattern, ua, re.I)
        if m:
            os_name = name
            if name in ('Android', 'iOS'):
                ver = m.group(m.lastindex) if m.lastindex else ''
                if ver:
                    os_name = f'{name} {ver}'
            break
    if not os_name:
        os_name = 'نامشخص'

    device = 'دسکتاپ'
    for pattern, name in _DEVICE_RULES:
        if re.search(pattern, ua, re.I):
            device = name
            break

    return {'browser': browser, 'os': os_name, 'device': device, 'raw': ua[:500]}


def record_security_event(request=None, *, user=None, username='', event_type='login',
                          severity='info', detail='', user_agent=None, ip=None,
                          session_key=None):
    """ثبت امنِ یک رویداد — هیچ‌وقت نباید جریان اصلی برنامه را بشکند."""
    try:
        ua = user_agent if user_agent is not None else (
            request.META.get('HTTP_USER_AGENT', '') if request is not None else '')
        parsed = parse_user_agent(ua)
        SecurityEvent.objects.create(
            user=user,
            username_snapshot=username or (getattr(user, 'username', '') or ''),
            event_type=event_type,
            severity=severity,
            ip_address=ip if ip is not None else (client_ip(request) if request is not None else None),
            user_agent=parsed['raw'],
            browser=parsed['browser'],
            os=parsed['os'],
            device=parsed['device'],
            session_key=(session_key if session_key is not None
                         else (request.session.session_key if request is not None
                               and hasattr(request, 'session') else '')) or '',
            detail=detail or '',
        )
    except Exception:  # pragma: no cover — لاگ‌برداری هرگز نباید خطا بدهد
        pass
