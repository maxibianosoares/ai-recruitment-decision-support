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
        "Thank you for your interest.",
    ]

    send_mail(
        subject=subject,
        message="\n".join(body_lines),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[candidate_email],
        fail_silently=False,
    )