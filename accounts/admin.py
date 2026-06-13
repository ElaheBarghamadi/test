from django.contrib import admin

# Register your models here.
# accounts/admin.py
from django.contrib import admin
from .models import Grade, User

admin.site.register(Grade)
admin.site.register(User)