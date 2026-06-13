# panel_admin/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path('', views.admin_dashboard, name='admin_dashboard'),
    path('users/', views.manage_users, name='manage_users'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/import/', views.import_users_from_file, name='import_users_from_file'),
    path('users/download-template/', views.download_users_template, name='download_users_template'),
    path('users/<int:user_id>/get/', views.get_user, name='get_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('exams/', views.manage_exams, name='manage_exams'),
    path('exams/<int:exam_id>/', views.view_exam_detail, name='exam_detail'),
    path('exams/<int:exam_id>/toggle/', views.toggle_exam_status, name='toggle_exam_status'),
    path('exams/<int:exam_id>/delete/', views.delete_exam, name='delete_exam'),
    path('analytics/exams/', views.exam_analytics, name='exam_analytics'),
    path('analytics/students/', views.student_analytics, name='student_analytics'),
    path('settings/', views.system_settings, name='system_settings'),
    path('logs/', views.system_logs, name='system_logs'),
    path('backup/', views.backup_data, name='backup_data'),
    path('exams/<int:exam_id>/cheats/', views.exam_cheats_api, name='exam_cheats_api'),
]
