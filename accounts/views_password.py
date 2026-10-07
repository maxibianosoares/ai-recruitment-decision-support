"""
TASK K (2026-10-07): Forgot Password / Password Reset.

Built entirely on Django's own password-reset machinery
(django.contrib.auth.views + default_token_generator) -- no custom
token scheme. Django's token already:

  * is signed with SECRET_KEY and tied to the user's current password
    hash and last_login, so it stops working the moment the password
    is changed (a link can only be used once);
  * expires after settings.PASSWORD_RESET_TIMEOUT seconds;
  * is rejected if the uid or token is tampered with.

Three deliberate hardening choices on top of the defaults:

1. The reset link is built from settings.SITE_URL, NOT from the
   request's Host header, so a forged Host header cannot make the
   email point at an attacker's site (password-reset poisoning).
2. Sending is wrapped so an SMTP/API failure never turns into a 500
   page -- a 500 would only happen for REGISTERED emails and would
   reveal that the account exists. The failure is logged instead.
3. The "email sent" page is shown for every submitted address,
   registered or not.
"""

import logging

from django import forms
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.urls import reverse_lazy

logger = logging.getLogger(__name__)

_INPUT_CLASS = "form-control"


class ForgotPasswordForm(PasswordResetForm):
    """PasswordResetForm with site styling and failure-safe sending."""

    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": _INPUT_CLASS,
                "autocomplete": "email",
                "autofocus": True,
            }
        ),
    )

    def send_mail(self, *args, **kwargs):
        try:
            super().send_mail(*args, **kwargs)
        except Exception:
            # Django's own send_mail already logs and swallows a failed
            # send(); this is a second safety net for everything around
            # it (e.g. a template error) so that NOTHING can turn the
            # response into a 500 only for registered emails -- that
            # would reveal which emails have accounts.
            logger.exception("Password reset email could not be sent")


class ForgotPasswordView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    form_class = ForgotPasswordForm
    success_url = reverse_lazy("password_reset_done")
    from_email = None  # falls back to settings.DEFAULT_FROM_EMAIL

    def form_valid(self, form):
        # extra_email_context carries the trusted site address and the
        # link lifetime into the email template.
        self.extra_email_context = {
            "site_url": settings.SITE_URL,
            "valid_minutes": int(settings.PASSWORD_RESET_TIMEOUT // 60),
        }
        return super().form_valid(form)


class ForgotPasswordDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class StyledSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("new_password1", "new_password2"):
            self.fields[name].widget.attrs.update(
                {"class": _INPUT_CLASS, "autocomplete": "new-password"}
            )


class ResetPasswordConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("password_reset_complete")
    # Django swaps the token for a session marker and redirects to
    # .../set-password/ so the token is not left in the URL/Referer.
    post_reset_login = False


class ResetPasswordCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"