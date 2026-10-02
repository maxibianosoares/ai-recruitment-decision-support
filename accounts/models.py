from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.auth.validators import UnicodeUsernameValidator


class CaseInsensitiveUserManager(UserManager):
    """
    TASK F follow-up (2026-10-02): Django's default
    get_by_natural_key() does an exact-match lookup on USERNAME_FIELD.
    Now that USERNAME_FIELD is "email" (see User below), that would
    make login/admin lookups case-sensitive on email, which is not how
    email addresses behave anywhere else in this app (login_view
    previously matched case-insensitively; RegisterForm.clean_email()
    already rejects a new signup that only differs by case). This
    override keeps that same behavior for every caller that
    authenticates via the ORM's natural-key lookup (authenticate(),
    the admin login form, manage.py changepassword, etc.), not just
    our own login view.
    """

    def get_by_natural_key(self, username):
        case_insensitive_field = f"{self.model.USERNAME_FIELD}__iexact"
        return self.get(**{case_insensitive_field: username})


class Department(models.Model):

    name = models.CharField(
        max_length=150,
        unique=True
    )

    code = models.CharField(
        max_length=20,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class Position(models.Model):

    name = models.CharField(
        max_length=150,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class Role(models.Model):

    name = models.CharField(
        max_length=50,
        unique=True
    )

    permissions = models.ManyToManyField(
        "Permission",
        blank=True
    )

    def __str__(self):
        return self.name
    
class User(AbstractUser):

    # TASK F follow-up (2026-10-02): AbstractUser's default `username`
    # has unique=True, which rejected registration/user-creation
    # whenever two people happened to pick the same display name --
    # reported after hitting it while testing registration.
    #
    # Django will not allow a non-unique field to stay the model's
    # USERNAME_FIELD (system check auth.E003 -- "must be unique
    # because it is named as the USERNAME_FIELD"), so making username
    # non-unique requires making something ELSE the real unique
    # identifier. Login is already email + password only (see
    # login_view in views.py), so email becomes USERNAME_FIELD below,
    # with its own unique=True. username stays a required, ordinary
    # (non-unique) display field; REQUIRED_FIELDS lists it so
    # `createsuperuser` still asks for it.
    #
    # Known trade-off, accepted deliberately: Django's own /admin/
    # login form authenticates via ModelBackend against USERNAME_FIELD
    # too -- so /admin/ now effectively logs in by email as well
    # (whatever is typed into its "username" box is looked up as an
    # email). This was not separately re-pointed at username, because
    # doing so would reintroduce the exact uniqueness requirement this
    # change removes.
    username = models.CharField(
        max_length=150,
        unique=False,
        validators=[UnicodeUsernameValidator()],
        help_text=(
            "150 characters or fewer. Letters, digits and @/./+/-/_ only."
        ),
    )

    email = models.EmailField(
        unique=True
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = CaseInsensitiveUserManager()

    ROLE_CHOICES = [

        ("super_admin", "Super Administrator"),

        ("admin", "Administrator"),

        ("hr", "HR Officer"),

        ("reviewer", "Reviewer"),

        ("interviewer", "Interviewer"),

        ("candidate", "Candidate"),

    ]


    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )


    employee_id = models.CharField(

        max_length=50,

        blank=True,

        null=True,

        unique=True

    )

    phone = models.CharField(
        max_length=30,
        blank=True,
        null=True

    )


    profile_photo = models.ImageField(

        upload_to="profile/",

        blank=True,

        null=True

    )

    department = models.ForeignKey(

        Department,

        on_delete=models.SET_NULL,

        blank=True,

        null=True

    )
    position = models.ForeignKey(

        Position,

        on_delete=models.SET_NULL,

        blank=True,

        null=True

    )
    is_verified = models.BooleanField(

        default=False

    )

    email_verified_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(

        auto_now_add=True

    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):

        return self.username


class Permission(models.Model):

    code = models.CharField(
        max_length=100,
        unique=True
    )

    name = models.CharField(
        max_length=255
    )

    description = models.TextField(
        blank=True,
        null=True
    )


    def __str__(self):

        return self.name



class RolePermission(models.Model):

    ROLE_CHOICES = [
        ("super_admin", "Super Administrator"),
        ("admin", "Administrator"),
        ("hr", "HR Officer"),
        ("reviewer", "Reviewer"),
        ("interviewer", "Interviewer"),
        ("candidate", "Candidate"),
    ]


    role = models.CharField(

        max_length=30,

        choices=ROLE_CHOICES

    )


    permissions = models.ManyToManyField(

        Permission,
        blank=True

    )

    def __str__(self):

        return self.role