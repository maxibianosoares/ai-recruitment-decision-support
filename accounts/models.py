from django.db import models
from django.contrib.auth.models import AbstractUser


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


