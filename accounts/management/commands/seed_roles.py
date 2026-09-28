from django.core.management.base import BaseCommand

from accounts.models import Role, Permission


RECRUITMENT_MANAGE_CODE = "recruitment_manage"

# User Management is more sensitive than recruitment tooling -- it
# can create/edit/delete other users' accounts -- so unlike
# recruitment_manage (granted to every non-Candidate role), these
# four codes are granted ONLY to the roles listed in
# USER_MANAGEMENT_ALLOWED_ROLES below, per explicit decision (Phase
# 29 follow-up audit, 2026-09-28).
USER_MANAGEMENT_PERMISSION_DEFS = [
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

USER_MANAGEMENT_ALLOWED_ROLES = [
    "Super Admin",
    "Administrator",
]


class Command(BaseCommand):

    def handle(self, *args, **kwargs):

        roles = [

            "Super Admin",

            "Administrator",

            "HR Officer",

            "Reviewer",

            "Interviewer",

            "Candidate"

        ]

        for role in roles:

            Role.objects.get_or_create(

                name=role

            )

        # Keep fresh installs consistent with the
        # 0003_grant_recruitment_manage_permission data migration:
        # every non-Candidate role gets access to internal
        # recruitment tooling; Candidate never does. Safe/idempotent
        # to re-run -- never removes a permission from any role.
        permission, _ = Permission.objects.get_or_create(
            code=RECRUITMENT_MANAGE_CODE,
            defaults={
                "name": "Manage Recruitment (Jobs, Ranking, Candidate Review)"
            }
        )

        for role in Role.objects.exclude(name="Candidate"):
            role.permissions.add(permission)

        # Companion to the 0004_grant_user_management_permission data
        # migration: keeps fresh installs consistent with existing
        # databases. Only Super Admin and Administrator get User
        # Management access -- HR Officer, Reviewer, Interviewer, and
        # Candidate get none of it. Uses an explicit include-list
        # (Role.objects.filter(name__in=...)), not an exclude-list,
        # so a future new role never gets this access by accident.
        # Safe/idempotent to re-run -- never removes a permission
        # from any role.
        user_mgmt_permissions = []

        for code, name, description in USER_MANAGEMENT_PERMISSION_DEFS:

            permission, _ = Permission.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": description
                }
            )

            user_mgmt_permissions.append(permission)

        for role in Role.objects.filter(
            name__in=USER_MANAGEMENT_ALLOWED_ROLES
        ):
            for permission in user_mgmt_permissions:
                role.permissions.add(permission)

        self.stdout.write(

            self.style.SUCCESS(

                "Roles created successfully."

            )

        )