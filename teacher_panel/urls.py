# teacher_panel/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.teacher_dashboard, name='teacher_dashboard'),
    path('exam/create/', views.create_exam, name='create_exam'),
    path('exam/<int:exam_id>/edit/', views.edit_exam, name='edit_exam'),
    path('exam/<int:exam_id>/edit-info/', views.edit_exam_info, name='edit_exam_info'),
    path('exam/<int:exam_id>/question/add/', views.add_question, name='add_question'),
    path('exam/<int:exam_id>/question/<int:question_id>/edit/', views.edit_question, name='edit_question'),
    path('exam/<int:exam_id>/question/<int:question_id>/delete/', views.delete_question, name='delete_question'),
    path('exam/<int:exam_id>/grade/', views.grade_exam, name='grade_exam'),
    path('exam/<int:exam_id>/results/', views.exam_results, name='exam_results'),
    path('exam/<int:exam_id>/toggle-status/', views.toggle_exam_status, name='toggle_exam_status'),
    path('exam/<int:exam_id>/delete/', views.delete_exam, name='delete_exam'),
    path('exam/<int:exam_id>/print/', views.print_exam_paper, name='print_exam_paper'),
    path('exam/<int:exam_id>/print-answers/', views.print_answer_sheet, name='print_answer_sheet'),
    # path('exam/<int:exam_id>/download/<str:paper_type>/', views.download_pdf, name='download_pdf'),
    path('save-score/', views.save_score, name='save_score'),
    path('api/students/', views.get_students_api, name='get_students_api'),

    # مسیرهای جدید
    path('exam/<int:exam_id>/settings/', views.exam_settings, name='exam_settings'),
    path('exam/<int:exam_id>/cheats-report/', views.exam_cheats_report, name='exam_cheats_report'),
    path('exam/<int:exam_id>/student-answers/', views.view_student_answers, name='view_student_answers'),
    path('exam/<int:exam_id>/question/<int:question_id>/teacher-answer/', views.add_teacher_answer,
         name='add_teacher_answer'),
]