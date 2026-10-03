"""
Injects role-permission flags into every template's context, so
templates/base.html's sidebar (and any other template) can hide
links a user cannot actually access, without duplicating the same
Role/Permission lookup logic in every view.

This is presentation only -- it decides what to SHOW. The actual
access control is still enforced server-side by @permission_required
on each view (see accounts/decorators.py, talent/views.py); a link
being hidden here is never the only thing standing between a user
and a protected page.

TASK H (2026-10-03): also injects PILOT_MODE (settings.py, default
False) so templates/base.html can show the CSC pilot banner. Purely
presentational, same as everything else in this file -- no AI
pipeline, scoring, or access-control behavior is affected by this.
"""

from django.conf import settings


def _has_permission(user, code):

    if not getattr(user, "is_authenticated", False):
        return False

    role_id = getattr(user, "role_id", None)

    if role_id is None:
        return False

    return user.role.permissions.filter(code=code).exists()


def permissions(request):

    user = getattr(request, "user", None)

    return {
        "can_manage_recruitment": _has_permission(
            user, "recruitment_manage"
        ),
        "can_manage_users": _has_permission(
            user, "user_view"
        ),
        "PILOT_MODE": settings.PILOT_MODE,
    }