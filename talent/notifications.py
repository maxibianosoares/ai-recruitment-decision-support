"""
FINAL FINISHING SESSION (2026-10-05) -- Notification #1: AI screening
completed.

Separate module (not inside talent/views.py) because the sender is
ai_engine's background worker (a management command), not an HTTP
view -- importing talent.views from a management command would pull
in view-only dependencies unnecessarily. Mirrors the EXISTING
Brevo-backed send_mail() call shape already used by
talent/views.py._send_candidate_outcome_email() (Notification #2) --
no new email system, no new backend, same EMAIL_BACKEND setting.

Candidate-safe by construction: only the job title, the fact that AI
screening has completed, the AI recommendation label, and the
candidate-facing feedback text (application.ai_feedback -- the same
field already shown on the candidate's own Candidate Detail page) are
included. Never raw prompts, API keys, RAG/legal evidence text, or
internal scoring internals. Explicitly states this is NOT the final
recruitment decision (Section 17/18 of the task) -- the human review
stage is still ahead.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse


def application_detail_url(application):
    """
    Absolute link to the candidate's own application page
    (/ranking/<application id>/), which shows the AI recommendation
    details and the status. The candidate must be logged in as the
    account that applied; anyone else gets a permission error from the
    page itself, so the link carries no secret.

    Built from settings.SITE_URL because emails are sent from the
    background worker, where there is no request to read the host from.
    """
    path = reverse("candidate_detail", args=[application.id])
    return f"{settings.SITE_URL}{path}"


def send_ai_screening_completed_email(application):
    """
    Notification #1. Call ONLY after recruitment_pipeline() has
    returned successfully (application.ai_status == "SUCCESS") --
    never for ai_status in (QUEUED, PROCESSING, FAILED), and never as
    a stand-in for Notification #2 (the final human decision email,
    unchanged -- see talent/views.py._send_candidate_outcome_email()).

    Raises on failure. The caller (the background worker) must catch
    this and must NOT let it change application.ai_status or any
    other application field -- per Section 24, an email failure must
    never roll back or corrupt the AI/application state.
    """

    candidate_email = (application.candidate.email or "").strip()

    if not candidate_email:
        raise ValueError("Candidate has no email address on file.")

    subject = f"AI screening completed: {application.job.title}"

    body_lines = [
        f"Dear {application.candidate.full_name},",
        "",
        f"Your application for the {application.job.title} position "
        "has completed the AI-assisted screening stage.",
        "",
        "AI screening recommendation: "
        f"{application.ai_decision or 'Consider'}",
    ]

    if application.ai_feedback:
        body_lines += [
            "",
            "Summary:",
            application.ai_feedback,
        ]

    body_lines += [
        "",
        "IMPORTANT: this is an AI-generated screening recommendation, "
        "not a final recruitment decision. Your application will now "
        "be reviewed by an authorized human recruitment officer, who "
        "will make the final decision. You will receive a separate "
        "notification once that final decision has been made.",
        "",
        "View the full AI recommendation details (log in with the "
        "account you applied with):",
        application_detail_url(application),
        "",
        "Thank you for your interest.",
    ]

    send_mail(
        subject=subject,
        message="\n".join(body_lines),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[candidate_email],
        fail_silently=False,
    )


def send_document_issue_email(application):
    """
    TASK I: tells the candidate that their CV could not be read well
    enough for AI screening, and that they can upload a replacement.

    This is NOT Notification #1 (AI screening completed) and NOT
    Notification #2 (final human decision) -- it is sent when an
    application stops at DOCUMENT_INVALID / EXTRACTION_FAILED, i.e.
    before any AI screening happened. It must never claim the
    candidate was screened.

    Candidate-safe by construction: only the job title and the
    candidate-facing reason already stored in ai_feedback. Raises on
    failure; the caller (the worker) catches it and must not let it
    change ai_status.
    """

    candidate_email = (application.candidate.email or "").strip()

    if not candidate_email:
        raise ValueError("Candidate has no email address on file.")

    subject = f"Action needed on your application: {application.job.title}"

    body_lines = [
        f"Dear {application.candidate.full_name},",
        "",
        f"Thank you for applying for the {application.job.title} "
        "position.",
        "",
        "We could not read your CV well enough to start the AI-assisted "
        "screening, so your application has NOT been screened yet.",
    ]

    if application.ai_feedback:
        body_lines += ["", "Reason:", application.ai_feedback]

    body_lines += [
        "",
        "What to do: log in, open the position again and upload a "
        "clearer or digitally-generated PDF of your CV. Your "
        "application will then be screened.",
        "",
        "View your application status (log in with the account you "
        "applied with):",
        application_detail_url(application),
        "",
        "Thank you for your interest.",
    ]

    send_mail(
        subject=subject,
        message="\n".join(body_lines),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[candidate_email],
        fail_silently=False,
    )