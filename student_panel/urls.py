# student_panel/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.student_dashboard, name='student_dashboard'),
    path('exam/<str:hashed_exam_id>/', views.take_exam, name='take_exam'),
    path('submit/<str:hashed_exam_id>/', views.submit_exam, name='submit_exam'),
    path('thanks/<str:hashed_exam_id>/', views.exam_thanks, name='exam_thanks'),
    path('result/<int:exam_id>/', views.exam_result_detail, name='exam_result_detail'),
    path('check-exam-time/<str:hashed_exam_id>/', views.check_exam_time, name='check_exam_time'),
    path('save-answer/', views.save_answer, name='save_answer'),
    path('save-all-answers/', views.save_all_answers, name='save_all_answers'),
    path('save-answer-image/', views.save_answer_image, name='save_answer_image'),
    path('remove-answer-image/', views.remove_answer_image, name='remove_answer_image'),
    path('log-cheat/', views.log_cheat, name='log_cheat'),
]