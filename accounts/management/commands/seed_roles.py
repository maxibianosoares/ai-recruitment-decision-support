from django.core.management.base import BaseCommand

from accounts.models import Role, Permission


RECRUITMENT_MANAGE_CODE = "recruitment_manage"


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

        self.stdout.write(

            self.style.SUCCESS(

                "Roles created successfully."

            )

        )
