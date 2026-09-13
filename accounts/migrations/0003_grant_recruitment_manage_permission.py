"""
Registration/RBAC feature -- safety migration.

This migration introduces ONE new permission code,
"recruitment_manage", which the views that were previously only
@login_required (create_job, candidate_ranking, ranking_by_job,
ranking_jobs, candidate_detail's staff branch, test_semantic) now
require via @permission_required.

Because accounts.seed_roles only ever created Role rows by name and
never assigned any Permission to them, simply adding
@permission_required to those views with NO corresponding data
change would lock out every existing Super Admin/Administrator/HR
Officer/Reviewer/Interviewer user the moment this ships -- their
Role rows have zero permissions attached today, so the decorator's
`user.role.permissions.filter(code=...).exists()` check would fail
for everyone, including roles that obviously must keep this access.

This migration is the fix: it creates the "recruitment_manage"
Permission and attaches it to every existing Role EXCEPT the one
named "Candidate" (case-insensitive match, since seed_roles' exact
casing -- "Candidate" -- is what's expected, but this migration
does not assume seed_roles has even run yet). If a "Candidate" role
does not exist yet, none is created here -- registration will
create/attach it as needed at runtime.

Idempotent and safe to re-run: uses get_or_create throughout, and
never removes any existing permission from any role.
"""

from django.db import migrations


PERMISSION_CODE = "recruitment_manage"
PERMISSION_NAME = "Manage Recruitment (Jobs, Ranking, Candidate Review)"


def grant_recruitment_manage_to_existing_roles(apps, schema_editor):

    Role = apps.get_model("accounts", "Role")
    Permission = apps.get_model("accounts", "Permission")

    permission, _ = Permission.objects.get_or_create(
        code=PERMISSION_CODE,
        defaults={
            "name": PERMISSION_NAME,
            "description": (
                "Access to internal recruitment tooling: creating "
                "jobs, viewing candidate rankings, and reviewing "
                "individual candidate screening results as staff."
            )
        }
    )

    for role in Role.objects.all():

        if role.name.strip().lower() == "candidate":
            # Candidates must NOT receive this permission -- this is
            # the entire point of the migration, not an oversight.
            continue

        role.permissions.add(permission)


def reverse_noop(apps, schema_editor):
    # Deliberately not removing the permission on reverse -- doing so
    # could strip access that was also granted manually in the admin
    # after this migration ran. Reversing this migration is a no-op;
    # remove the permission by hand via Django Admin if truly needed.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_user_email_verified_at'),
    ]

    operations = [
        migrations.RunPython(
            grant_recruitment_manage_to_existing_roles,
            reverse_noop
        ),
    ]
