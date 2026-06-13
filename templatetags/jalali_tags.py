# teacher_panel/templatetags/jalali_tags.py
from django import template
import jdatetime
from django.utils import timezone

register = template.Library()

@register.filter
def to_jalali(date):
    if not date:
        return ''
    try:
        if timezone.is_naive(date):
            date = timezone.make_aware(date)
        jd = jdatetime.datetime.fromgregorian(datetime=date)
        return jd.strftime('%Y/%m/%d %H:%M')
    except:
        return ''