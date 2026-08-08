from django import forms

from django.contrib.auth.forms import UserCreationForm

from .models import User


class UserForm(UserCreationForm):

    class Meta:

        model = User

        fields = [

            "username",

            "first_name",

            "last_name",

            "email",

            "employee_id",

            "department",

            "position",

            "role",

            "phone",

            "profile_photo",

            "is_active",

            "is_verified"

        ]