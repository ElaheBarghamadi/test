# teacher_panel/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # داشبورد
    path('dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    # مدیریت آزمون
    path('exam/create/', views.create_exam, name='create_exam'),
    path('exam/<int:exam_id>/edit/', views.edit_exam, name='edit_exam'),
    path('exam/<int:exam_id>/edit-info/', views.edit_exam_info, name='edit_exam_info'),
    path('exam/<int:exam_id>/settings/', views.exam_settings, name='exam_settings'),
    path('exam/<int:exam_id>/delete/', views.delete_exam, name='delete_exam'),
    path('exam/<int:exam_id>/toggle-status/', views.toggle_exam_status, name='toggle_exam_status'),

    # مدیریت سوالات
    path('exam/<int:exam_id>/question/add/', views.add_question, name='add_question'),
    path('exam/<int:exam_id>/question/<int:question_id>/edit/', views.edit_question, name='edit_question'),
    path('exam/<int:exam_id>/question/<int:question_id>/delete/', views.delete_question, name='delete_question'),
    path('exam/<int:exam_id>/question/<int:question_id>/teacher-answer/', views.add_teacher_answer,
         name='add_teacher_answer'),
    path('exam/<int:exam_id>/bulk-upload/', views.bulk_upload_questions, name='bulk_upload_questions'),
    path('download-template/', views.download_question_template, name='download_question_template'),

    # تصحیح و نمره‌دهی
    path('exam/<int:exam_id>/grade/', views.grade_exam, name='grade_exam'),
    path('exam/<int:exam_id>/results/', views.exam_results, name='exam_results'),
    path('exam/<int:exam_id>/results/csv/', views.export_results_csv, name='export_results_csv'),
    path('exam/<int:exam_id>/duplicate/', views.duplicate_exam, name='duplicate_exam'),
    path('exam/<int:exam_id>/student-answers/', views.view_student_answers, name='view_student_answers'),
    path('exam/<int:exam_id>/cheats-report/', views.exam_cheats_report, name='exam_cheats_report'),
    path('bank/', views.question_bank, name='question_bank'),
    path('bank/<int:bank_id>/delete/', views.delete_bank_question, name='delete_bank_question'),
    path('bank/<int:bank_id>/move/', views.bank_question_move, name='bank_question_move'),
    path('bank/folder/add/', views.bank_folder_add, name='bank_folder_add'),
    path('bank/folder/<int:folder_id>/rename/', views.bank_folder_rename, name='bank_folder_rename'),
    path('bank/folder/<int:folder_id>/delete/', views.bank_folder_delete, name='bank_folder_delete'),
    path('bank/<int:bank_id>/import/', views.import_bank_question, name='import_bank_question'),
    path('groups/', views.groups, name='groups'),
    path('exam/<int:exam_id>/apply-group/', views.apply_group_to_exam, name='apply_group_to_exam'),
    path('announce/', views.announcement_create, name='announcement_create'),
    path('announce/<int:ann_id>/delete/', views.announcement_delete, name='announcement_delete'),
    path('save-score/', views.save_score, name='save_score'),

    # چاپ
    path('exam/<int:exam_id>/print/', views.print_exam_paper, name='print_exam_paper'),
    path('exam/<int:exam_id>/print-answers/', views.print_answer_sheet, name='print_answer_sheet'),

    # API
    path('api/students/', views.get_students_api, name='get_students_api'),
]