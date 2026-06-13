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