from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

from .forms import RegisterForm
from .models import Role
from .tokens import email_verification_token


User = get_user_model()


def _send_verification_email(request, user):

    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)

    verify_path = reverse(
        "verify_email",
        kwargs={"uidb64": uidb64, "token": token}
    )

    verify_url = request.build_absolute_uri(verify_path)

    send_mail(
        subject="Verify your email -- AI Civil Service Recruitment",
        message=(
            f"Hi {user.first_name or user.username},\n\n"
            f"Please verify your email address by opening this link:\n"
            f"{verify_url}\n\n"
            f"If you did not create this account, you can ignore this "
            f"email."
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[user.email],
        fail_silently=False
    )


def register_view(request):

    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():

            user = form.save(commit=False)

            # Role is assigned here, server-side, from a fixed value
            # -- never from request data. RegisterForm.Meta.fields
            # does not include "role" at all, so this is the only
            # place a role is ever set for a self-registered account.
            candidate_role, _ = Role.objects.get_or_create(
                name="Candidate"
            )

            user.role = candidate_role
            user.is_verified = False
            # is_active stays True -- login is blocked by the
            # explicit is_verified check in login_view, not by
            # Django's is_active flag. This keeps authenticate()
            # able to distinguish "wrong password" from "correct
            # password, not verified yet" so login_view can show the
            # right message for each case (a blanket is_active=False
            # would make both cases look identical to authenticate()).
            user.save()

            try:
                _send_verification_email(request, user)
            except Exception as e:
                # Registration itself still succeeded -- don't lose
                # the created account over an SMTP/API hiccup. The
                # user can use "resend verification" once mail is
                # working. But the failure must not vanish silently --
                # print it so it's visible in Render's runtime logs,
                # since this swallowed every previous email failure
                # without a trace.
                print(f"Verification email send failed (register): {e}")

            return render(
                request,
                "accounts/register_success.html",
                {"email": user.email}
            )

    else:

        form = RegisterForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form}
    )


def verify_email_view(request, uidb64, token):

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is not None and email_verification_token.check_token(
        user, token
    ):

        user.is_verified = True
        user.email_verified_at = timezone.now()
        user.save()

        return render(request, "accounts/verify_success.html")

    return render(request, "accounts/verify_failed.html")


def resend_verification_view(request):

    sent = False

    if request.method == "POST":

        email = request.POST.get("email", "").strip()

        user = User.objects.filter(
            email__iexact=email,
            is_verified=False
        ).first()

        if user is not None:
            try:
                _send_verification_email(request, user)
            except Exception as e:
                print(f"Verification email send failed (resend): {e}")

        # Always show the same confirmation regardless of whether
        # the email exists or was already verified -- do not reveal
        # account existence to an anonymous requester.
        sent = True

    return render(
        request,
        "accounts/resend_verification.html",
        {"sent": sent}
    )