from django import template
import jdatetime

register = template.Library()

@register.filter
def to_jalali(date):
    """تبدیل تاریخ میلادی به شمسی"""
    if not date:
        return ''
    try:
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date)
        return jalali_date.strftime('%Y/%m/%d %H:%M')
    except:
        return date.strftime('%Y/%m/%d %H:%M')

@register.filter
def to_jalali_date(date):
    """تبدیل تاریخ میلادی به شمسی (فقط تاریخ)"""
    if not date:
        return ''
    try:
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date)
        return jalali_date.strftime('%Y/%m/%d')
    except:
        return date.strftime('%Y/%m/%d')

@register.filter
def to_jalali_time(date):
    """تبدیل تاریخ میلادی به شمسی (فقط ساعت)"""
    if not date:
        return ''
    try:
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date)
        return jalali_date.strftime('%H:%M')
    except:
        return date.strftime('%H:%M')