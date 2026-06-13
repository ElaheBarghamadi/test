from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required


def login_view(request):
    """صفحه ورود یکسان برای همه نقش‌ها"""
    # اگر کاربر وارد شده بود، بره به پنل خودش
    if request.user.is_authenticated:
        if request.user.role == 'admin':
            return redirect('admin_dashboard')
        elif request.user.role == 'teacher':
            return redirect('teacher_dashboard')
        elif request.user.role == 'student':
            return redirect('student_dashboard')
        return redirect('/')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            auth_login(request, user)

            # هدایت بر اساس نقش
            if user.role == 'admin':
                return redirect('admin_dashboard')
            elif user.role == 'teacher':
                return redirect('teacher_dashboard')
            elif user.role == 'student':
                return redirect('student_dashboard')
            return redirect('/')
        else:
            return render(request, 'login.html', {'error': 'نام کاربری یا رمز عبور اشتباه است'})

    return render(request, 'login.html')


def logout_view(request):
    """خروج از سیستم"""
    logout(request)
    return redirect('login')


# ========== صفحات خطا ==========

def bad_request(request, exception=None):
    """خطای 400 - درخواست نادرست"""
    return render(request, '400.html', status=400)


def permission_denied(request, exception=None):
    """خطای 403 - دسترسی غیرمجاز"""
    return render(request, '403.html', status=403)


def page_not_found(request, exception=None):
    """خطای 404 - صفحه یافت نشد"""
    return render(request, '404.html', status=404)


def server_error(request):
    """خطای 500 - خطای داخلی سرور"""
    return render(request, '500.html', status=500)
