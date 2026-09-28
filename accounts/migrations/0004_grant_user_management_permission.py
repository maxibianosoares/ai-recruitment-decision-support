"""
Registration/RBAC feature -- safety migration (companion to 0003).

Grants the four User Management permission codes referenced by
accounts/views.py (user_list, user_detail, user_create, user_edit,
user_delete -- all @permission_required-gated) and by
accounts/context_processors.py's can_manage_users flag, which were
never created by any prior migration -- confirmed by a full-codebase
search finding zero Permission.objects.create/get_or_create calls for
these codes anywhere except this migration and seed_roles.py.

Unlike 0003 (which grants recruitment_manage to every role except
Candidate), User Management is more sensitive -- it can create,
edit, and delete other users' accounts -- so this migration grants
it ONLY to "Super Admin" and "Administrator" (case-insensitive
match), per an explicit decision recorded in this project's Phase 29
follow-up audit. HR Officer, Reviewer, Interviewer, and Candidate
receive none of these four permissions.

Idempotent and safe to re-run: uses get_or_create throughout, never
removes any existing permission from any role, and never touches
recruitment_manage or any other existing Permission/Role/User data.
"""

from django.db import migrations


PERMISSION_DEFS = [
    (
        "user_view",
        "View Users",
        "View the list of user accounts and their details."
    ),
    (
        "user_create",
        "Create Users",
        "Create new user accounts."
    ),
    (
        "user_edit",
        "Edit Users",
        "Edit existing user accounts."
    ),
    (
        "user_delete",
        "Delete Users",
        "Delete user accounts."
    ),
]

ALLOWED_ROLE_NAMES = ("super admin", "administrator")


def grant_user_management_to_allowed_roles(apps, schema_editor):

    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")

    permissions = []

    for code, name, description in PERMISSION_DEFS:

        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description
            }
        )

        permissions.append(permission)

    for role in Role.objects.all():

        if role.name.strip().lower() not in ALLOWED_ROLE_NAMES:
            # HR Officer, Reviewer, Interviewer, Candidate, and any
            # other role must NOT receive User Management access --
            # this is the entire point of restricting the grant loop
            # below, not an oversight.
            continue

        for permission in permissions:
            role.permissions.add(permission)


def reverse_noop(apps, schema_editor):
    # Deliberately not removing the permissions on reverse -- same
    # rationale as 0003: doing so could strip access also granted
    # manually in the admin after this migration ran. Reversing this
    # migration is a no-op; remove permissions by hand via Django
    # Admin if truly needed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_grant_recruitment_manage_permission'),
    ]

    operations = [
        migrations.RunPython(
            grant_user_management_to_allowed_roles,
            reverse_noop
        ),
    ]