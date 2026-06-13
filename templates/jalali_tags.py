# teacher_panel/templatetags/jalali_tags.py
from django import template
from django.utils import timezone
import jdatetime

register = template.Library()


@register.filter
def to_jalali(date):
    """تبدیل تاریخ میلادی به شمسی"""
    if not date:
        return ''

    if timezone.is_aware(date):
        date = timezone.localtime(date)

    # تبدیل به jdatetime
    try:
        jdate = jdatetime.datetime.fromgregorian(datetime=date)
        return jdate.strftime('%Y/%m/%d %H:%M')
    except:
        return date.strftime('%Y/%m/%d %H:%M')