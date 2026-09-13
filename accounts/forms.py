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


class RegisterForm(UserCreationForm):
    """
    Public self-registration form -- deliberately does NOT expose
    role, is_active, or is_verified (unlike UserForm above, which is
    for internal staff creating accounts of any role). Whatever the
    request sends for those fields is impossible to set here: they
    are not in Meta.fields, so Django's ModelForm never reads them
    from POST data in the first place. The view is also responsible
    for setting role="Candidate" itself after save(), never from
    form input.
    """

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )

    first_name = forms.CharField(
        required=True,
        label="Full name",
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    class Meta:

        model = User

        fields = [
            "username",
            "first_name",
            "email",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"class": "form-control"})
        self.fields["password1"].widget.attrs.update({"class": "form-control"})
        self.fields["password2"].widget.attrs.update({"class": "form-control"})

    def clean_email(self):

        email = self.cleaned_data["email"]

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        return email
