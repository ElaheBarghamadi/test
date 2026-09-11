"""اطلاعیه‌های قابل نمایش به دانش‌آموز (برای زنگوله نوار بالا)"""
from django.db.models import Q

from .models import Announcement


def announcements(request):
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False) or user.role != 'student':
        return {}
    qs = Announcement.objects.filter(Q(grade__isnull=True) | Q(grade_id=user.grade_id))
    return {'bell_announcements': list(qs[:8]), 'bell_count': qs.count()}
