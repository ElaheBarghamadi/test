from django.urls import path
from . import control_views as views

urlpatterns = [
    path('', views.control_dashboard, name='control_dashboard'),
    path('users/', views.control_users, name='control_users'),
    path('users/<int:user_id>/toggle/', views.control_toggle_user, name='control_toggle_user'),
    path('users/<int:user_id>/terminate-sessions/', views.control_terminate_sessions, name='control_terminate_sessions'),
]
