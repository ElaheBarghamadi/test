from django.contrib import admin

# Register your models here.
# exams/admin.py
from django.contrib import admin
from .models import Exam, Question, StudentAnswer, ExamAttempt, ExamSession, CheatAttempt, TeacherAnswer


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'teacher', 'grade', 'start_time', 'end_time', 'is_active']
    list_filter = ['is_active', 'grade']
    search_fields = ['title']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'exam', 'question_type', 'max_score', 'order']
    list_filter = ['question_type', 'exam']


@admin.register(StudentAnswer)
class StudentAnswerAdmin(admin.ModelAdmin):
    list_display = ['id', 'student', 'question', 'score_obtained', 'updated_at']
    list_filter = ['question__exam']


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ['id', 'student', 'exam', 'status', 'started_at', 'submitted_at']
    list_filter = ['status', 'exam']


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'student', 'exam', 'ip_address', 'is_active', 'started_at']
    list_filter = ['exam', 'is_active']


@admin.register(CheatAttempt)
class CheatAttemptAdmin(admin.ModelAdmin):
    list_display = ['id', 'session', 'cheat_type', 'created_at']
    list_filter = ['cheat_type', 'created_at']


@admin.register(TeacherAnswer)
class TeacherAnswerAdmin(admin.ModelAdmin):
    list_display = ['id', 'question', 'updated_at']