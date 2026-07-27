from django.urls import path

from .views import change_password_view, dashboard_view, login_view, logout_view, register_view

urlpatterns = [
    path('register/', register_view, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('change-password/', change_password_view, name='change_password'),
]
