from django.db import models

# Create your models here.
# exams/models.py
from django.db import models
from django.conf import settings
from accounts.models import Grade


# exams/models.py - فیلدهای جدید رو به کلاس Exam اضافه کن

class Exam(models.Model):
    """مدل آزمون"""
    title = models.CharField(max_length=200)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                limit_choices_to={'role': 'teacher'})
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE)
    duration_minutes = models.IntegerField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    students = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='exams',
                                      limit_choices_to={'role': 'student'})
    is_active = models.BooleanField(default=True)
    show_score_to_student = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    random_questions = models.BooleanField(default=False)

    # ========== فیلدهای جدید ==========

    # تنظیمات امنیتی و جلوگیری از تقلب
    enable_anti_cheat = models.BooleanField(default=True, verbose_name="فعال کردن سیستم تشخیص تقلب")
    prevent_tab_switch = models.BooleanField(default=True, verbose_name="جلوگیری از تغییر تب")
    prevent_copy_paste = models.BooleanField(default=True, verbose_name="جلوگیری از کپی/پیست")
    track_ip = models.BooleanField(default=True, verbose_name="ردیابی IP")
    TIMER_TYPE_CHOICES = [
        ('floating', 'تایم شناور (از لحظه شروع دانش‌آموز)'),
        ('fixed', 'تایم ثابت (همه تا زمان پایان مشخص)'),
    ]

    timer_type = models.CharField(
        max_length=20,
        choices=TIMER_TYPE_CHOICES,
        default='floating',
        verbose_name="نوع تایمر"
    )

    # تنظیمات نمایش سوالات
    show_questions_mode = models.CharField(
        max_length=20,
        choices=[('all', 'همه سوالات در یک صفحه'), ('one_by_one', 'هر سوال در یک صفحه')],
        default='one_by_one',
        verbose_name="نحوه نمایش سوالات"
    )
    show_back_button = models.BooleanField(default=True, verbose_name="نمایش دکمه بازگشت به سوال قبلی")

    # تنظیمات پاسخ تشریحی
    allow_teacher_answer = models.BooleanField(default=True, verbose_name="معلم می‌تواند پاسخ تشریحی وارد کند")

    # نمایش پاسخ‌ها بعد از اتمام آزمون
    show_answers_after_exam = models.BooleanField(default=False,
                                                  verbose_name="نمایش پاسخ صحیح به دانش‌آموز بعد از اتمام")

    def __str__(self):
        return f"{self.title}"


class Question(models.Model):
    """مدل سوال"""
    QUESTION_TYPES = [
        ('true_false', 'صحیح/غلط'),
        ('multiple_choice', 'تستی'),
        ('fill_blank', 'جاخالی'),
        ('short_answer', 'پاسخ کوتاه'),
        ('long_answer', 'پاسخ بلند'),
        ('image_answer', 'پاسخ تصویری'),
        ('matching', 'وصل کردنی'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField(blank=True)
    image = models.ImageField(upload_to='question_images/', null=True, blank=True)
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    max_score = models.DecimalField(max_digits=10, decimal_places=2, default=1.0)
    order = models.IntegerField(default=0)
    options = models.JSONField(default=list, blank=True)
    options_type = models.CharField(max_length=10,
                                    choices=[('text', 'متن'), ('image', 'تصویر'), ('mixed', 'متن+تصویر')],
                                    default='text')
    correct_answer = models.TextField(blank=True, null=True)
    blanks = models.JSONField(default=list, blank=True)
    matching_pairs = models.JSONField(default=list, blank=True)
    allow_image_answer = models.BooleanField(default=False)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"سوال {self.order}: {self.exam.title}"


class StudentAnswer(models.Model):
    """مدل پاسخ دانش‌آموز"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer_text = models.TextField(blank=True, null=True)
    answer_image = models.ImageField(upload_to='student_answers/', null=True, blank=True)
    score_obtained = models.FloatField(null=True, blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='graded_answers')
    graded_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['student', 'question']

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.question}"


class ExamAttempt(models.Model):
    """مدل تلاش دانش‌آموز برای آزمون"""
    STATUS_CHOICES = [
        ('not_started', 'شروع نشده'),
        ('in_progress', 'در حال انجام'),
        ('submitted', 'ثبت نهایی شده'),
        ('timeout', 'زمان تمام شده'),
    ]

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ['student', 'exam']

    def __str__(self):
        return f"{self.student} - {self.exam}"


# exams/models.py - اضافه کردن این مدل‌ها در انتهای فایل

class ExamSession(models.Model):
    """جلسه شرکت دانش‌آموز در آزمون"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='exam_sessions')
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='sessions')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['student', 'exam']

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.exam.title}"


class CheatAttempt(models.Model):
    """ثبت تلاش‌های تقلب"""
    CHEAT_TYPES = [
        ('tab_switch', 'تغییر تب'),
        ('copy_paste', 'کپی/پیست'),
        ('right_click', 'کلیک راست'),
        ('multiple_tabs', 'باز کردن چند تب'),
        ('different_ip', 'آی‌پی متفاوت'),
        ('inactivity', 'عدم فعالیت طولانی'),
        ('screenshot', 'اسکرین‌شات'),
        ('print_screen', 'چاپ صفحه'),
    ]

    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='cheats')
    cheat_type = models.CharField(max_length=50, choices=CHEAT_TYPES)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session.student.get_full_name()} - {self.get_cheat_type_display()}"


class ExamLog(models.Model):
    """لاگ فعالیت دانش‌آموز در آزمون"""
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=200)
    page_url = models.CharField(max_length=500, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.session.student.get_full_name()} - {self.action}"


class TeacherAnswer(models.Model):
    """پاسخ تشریحی معلم برای سوالات"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='teacher_answers')
    answer_text = models.TextField(blank=True, null=True)
    answer_image = models.ImageField(upload_to='teacher_answers/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"پاسخ معلم - {self.question}"
