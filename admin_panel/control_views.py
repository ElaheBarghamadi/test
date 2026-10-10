from datetime import timedelta

from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from exams.models import Exam, ExamAttempt, StudentAnswer, CheatAttempt
from .models import SiteVisit, SecurityEvent, record_security_event

User = get_user_model()
staff_required = user_passes_test(lambda u: u.is_authenticated and (u.is_staff or u.is_superuser), login_url='login')


def _range(request):
    try: days = int(request.GET.get('days', 30))
    except ValueError: days = 30
    days = days if days in (1, 7, 30, 90, 365) else 30
    return days, timezone.now() - timedelta(days=days)


@staff_required
def control_dashboard(request):
    days, since = _range(request)
    visits = SiteVisit.objects.filter(created_at__gte=since)
    today = timezone.localdate()
    daily_raw = (visits.annotate(day=TruncDate('created_at')).values('day').annotate(total=Count('id')).order_by('day'))
    daily_map = {x['day']: x['total'] for x in daily_raw}
    chart = []
    chart_days = min(days, 30)
    max_count = 1
    for i in range(chart_days - 1, -1, -1):
        day = today - timedelta(days=i); count = daily_map.get(day, 0)
        chart.append({'day': day, 'count': count}); max_count = max(max_count, count)
    for row in chart: row['height'] = max(3, round(row['count'] / max_count * 100))

    stats = {
        'visits': visits.count(), 'unique_ips': visits.exclude(ip_address=None).values('ip_address').distinct().count(),
        'active_users': visits.exclude(user=None).values('user').distinct().count(),
        'avg_ms': round(visits.aggregate(v=Avg('response_ms'))['v'] or 0),
        'errors': visits.filter(status_code__gte=400).count(), 'users': User.objects.count(),
        'exams': Exam.objects.count(), 'attempts': ExamAttempt.objects.count(),
    }
    context = {
        'days': days, 'stats': stats, 'chart': chart,
        'popular': visits.values('path').annotate(total=Count('id'), avg=Avg('response_ms')).order_by('-total')[:12],
        'devices': visits.values('device').annotate(total=Count('id')).order_by('-total')[:8],
        'browsers': visits.values('browser').annotate(total=Count('id')).order_by('-total')[:8],
        'statuses': visits.values('status_code').annotate(total=Count('id')).order_by('-total')[:10],
        'recent_visits': visits.select_related('user')[:20],
        'security_events': SecurityEvent.objects.select_related('user')[:15],
        'recent_users': User.objects.select_related('grade').order_by('-date_joined')[:10],
        'system': {'answers': StudentAnswer.objects.count(), 'cheats': CheatAttempt.objects.count(),
                   'submitted': ExamAttempt.objects.filter(status='submitted').count()},
    }
    return render(request, 'admin_panel/control_center.html', context)


@staff_required
def control_users(request):
    q = request.GET.get('q', '').strip()[:100]
    users = User.objects.select_related('grade').order_by('-date_joined')
    if q: users = users.filter(Q(username__icontains=q)|Q(first_name__icontains=q)|Q(last_name__icontains=q))
    return render(request, 'admin_panel/control_users.html', {'page': Paginator(users, 30).get_page(request.GET.get('page')), 'q': q})


@staff_required
@require_POST
def control_toggle_user(request, user_id):
    target = get_object_or_404(User, id=user_id)
    if target == request.user or (target.is_superuser and not request.user.is_superuser):
        return JsonResponse({'error': 'اجازه تغییر این حساب را ندارید.'}, status=403)
    target.is_active = not target.is_active; target.save(update_fields=['is_active'])
    record_security_event(request, user=target, event_type='profile_updated', severity='warning',
                          detail=f'وضعیت حساب از مرکز کنترل به {target.is_active} تغییر کرد')
    return redirect('control_users')


@staff_required
@require_POST
def control_terminate_sessions(request, user_id):
    target = get_object_or_404(User, id=user_id)
    killed = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        try: uid = session.get_decoded().get('_auth_user_id')
        except Exception: continue
        if str(uid) == str(target.id): session.delete(); killed += 1
    record_security_event(request, user=target, event_type='session_revoked', severity='warning', detail=f'{killed} نشست از مرکز کنترل بسته شد')
    return redirect('control_users')
