# student_panel/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.student_dashboard, name='student_dashboard'),
    path('exam/<int:exam_id>/', views.take_exam, name='take_exam'),
    path('submit/<int:exam_id>/', views.submit_exam, name='submit_exam'),
    path('thanks/<int:exam_id>/', views.exam_thanks, name='exam_thanks'),
    path('save-answer/', views.save_answer, name='save_answer'),
    path('save-answer-image/', views.save_answer_image, name='save_answer_image'),
    path('remove-answer-image/', views.remove_answer_image, name='remove_answer_image'),
    path('result/<int:exam_id>/', views.exam_result_detail, name='exam_result_detail'),
    path('check-exam-time/<int:exam_id>/', views.check_exam_time, name='check_exam_time'),
    path('log-cheat/', views.log_cheat, name='log_cheat'),
    path('check-time/<int:exam_id>/', views.check_exam_time, name='check_exam_time'),

]
