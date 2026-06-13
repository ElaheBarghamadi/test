from django.db import models

# Create your models here.
# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models


class Grade(models.Model):
    """پایه تحصیلی - فقط هفتم، هشتم، نهم"""
    GRADE_CHOICES = [
        ('7', 'هفتم'),
        ('8', 'هشتم'),
        ('9', 'نهم'),
    ]
    name = models.CharField(max_length=20, choices=GRADE_CHOICES, unique=True)

    def __str__(self):
        return self.get_name_display()


class User(AbstractUser):
    """مدل کاربر سفارشی"""
    ROLE_CHOICES = [
        ('admin', 'ادمین'),
        ('teacher', 'معلم'),
        ('student', 'دانش‌آموز'),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='student')
    grade = models.ForeignKey(Grade, on_delete=models.SET_NULL, null=True, blank=True)
    student_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
