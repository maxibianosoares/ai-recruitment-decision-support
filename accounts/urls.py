from django.urls import path
from .views import login_view, dashboard, logout_view, user_list, user_create, user_detail, user_edit, user_delete, profile

urlpatterns = [
    path(
        'login/',
        login_view,
        name='login'
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