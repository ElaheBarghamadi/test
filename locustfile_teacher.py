from locust import HttpUser, task, between
import random


class AnonymousUser(HttpUser):
    """کاربر بدون لاگین - فقط صفحات عمومی"""
    wait_time = between(1, 2)

    @task(3)
    def home_page(self):
        """صفحه اصلی"""
        self.client.get("/", name="Home Page")

    @task(5)
    def login_page(self):
        """صفحه ورود (GET)"""
        self.client.get("/login/", name="Login Page (GET)")

    @task(2)
    def student_login_page(self):
        """صفحه ورود دانش‌آموز"""
        self.client.get("/student/login/", name="Student Login Page")

    @task(2)
    def teacher_login_page(self):
        """صفحه ورود معلم"""
        self.client.get("/teacher/login/", name="Teacher Login Page")

    @task(1)
    def admin_login_page(self):
        """صفحه ورود ادمین"""
        self.client.get("/admin-panel/login/", name="Admin Login Page")

    @task(1)
    def static_files(self):
        """فایل‌های استاتیک (CSS)"""
        self.client.get("/static/admin/css/base.css", name="Static Files", catch_response=True)