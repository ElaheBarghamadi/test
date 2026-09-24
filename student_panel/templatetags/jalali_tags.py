# student_panel/templatetags/jalali_tags.py
import datetime as _dt

import jdatetime
from django import template
from django.utils import timezone

register = template.Library()


def _to_jalali(value, fmt):
    """تبدیل تاریخ میلادی به شمسی — با تبدیل به ساعت محلی (تهران)."""
    if not value:
        return ''
    try:
        if isinstance(value, _dt.datetime):
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return jdatetime.datetime.fromgregorian(datetime=value).strftime(fmt)
        if isinstance(value, _dt.date):
            return jdatetime.date.fromgregorian(date=value).strftime(fmt.split(' ')[0])
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        return value.strftime(fmt)
    except Exception:
        return ''


@register.filter
def to_jalali(value):
    return _to_jalali(value, '%Y/%m/%d %H:%M')


@register.filter
def to_jalali_date(value):
    return _to_jalali(value, '%Y/%m/%d')


@register.filter
def to_jalali_time(value):
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return ''
    return _to_jalali(value, '%H:%M')
