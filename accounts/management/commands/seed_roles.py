from django.core.management.base import BaseCommand

from accounts.models import Role


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

        self.stdout.write(

            self.style.SUCCESS(

                "Roles created successfully."

            )

        )