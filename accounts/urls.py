from django.urls import path
from .views import login_view, dashboard, logout_view, user_list, user_create, user_detail, user_edit, user_delete, profile
from .views_auth import register_view, verify_email_view, resend_verification_view
from .views_password import (
    ForgotPasswordView,
    ForgotPasswordDoneView,
    ResetPasswordConfirmView,
    ResetPasswordCompleteView,
)

urlpatterns = [
    path(
        'login/',
        login_view,
        name='login'
    ),
    path(
        'register/',
        register_view,
        name='register'
    ),
    path(
        'verify/<uidb64>/<token>/',
        verify_email_view,
        name='verify_email'
    ),
    path(
        'resend-verification/',
        resend_verification_view,
        name='resend_verification'
    ),
    # TASK K: forgot password / password reset (Django's own
    # PasswordReset views and token system -- see views_password.py).
    path(
        'forgot-password/',
        ForgotPasswordView.as_view(),
        name='password_reset'
    ),
    path(
        'forgot-password/sent/',
        ForgotPasswordDoneView.as_view(),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        ResetPasswordConfirmView.as_view(),
        name='password_reset_confirm'
    ),
    path(
        'reset/complete/',
        ResetPasswordCompleteView.as_view(),
        name='password_reset_complete'
    ),
    path(
        'dashboard/',
        dashboard,
        name='dashboard'
    ),

    path(
        'logout/',
        logout_view,
        name='logout'
    ),

    path(
        "users/",
        user_list,
        name="user_list"
    ),

    path(
        "users/create/",
        user_create,
        name="user_create"
    ),

    path(
        "users/<int:user_id>/",
        user_detail,
        name="user_detail"
    ),

    path(
        "users/<int:user_id>/edit/",
        user_edit,
        name="user_edit"
    ),

    path(
        "users/<int:user_id>/delete/",
        user_delete,
        name="user_delete"
    ),

    path(
        "profile/",
        profile,
        name="profile"
    ),

]