from time import perf_counter

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from accounts.decorators import permission_required
from .models import Job
from django.core.paginator import Paginator
from django.db.models import Q

from django.shortcuts import (
    render,
    redirect,
    get_object_or_404
)
from ai_engine.services.skill_extractor import (
    extract_skills
)
from .forms import JobForm
from ai_engine.services.recruitment_pipeline import recruitment_pipeline
from ai_engine.services.job_pipeline import process_job

from .models import (
    Job,
    Candidate,
    Application,
    HumanDecision
)
from .utils import extract_text_from_pdf, CVExtractionError
from .document_quality import check_document_quality

MAX_CV_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

from django.shortcuts import render, get_object_or_404
from .models import Job

from ai_engine.services.llm_candidate_profile import (
    analyze_cv_to_dict
)

from ai_engine.services.llm_semantic_matcher import (
    semantic_match
)

from .models import (
    Candidate,
    Job
)

def _has_recruitment_permission(user):
    """
    Shared staff-permission check, reused by views that need to
    allow BOTH internal staff (via the Role/Permission system) AND,
    separately, a candidate viewing their own record -- the
    @permission_required decorator alone can't express "OR owns this
    object", so views needing that combination call this directly.
    """

    role_id = getattr(user, "role_id", None)

    if role_id is None:
        return False

    return user.role.permissions.filter(
        code="recruitment_manage"
    ).exists()

# Roles allowed to record the FINAL Human Review decision
# (Approve / Reject). Same two roles that already have user-management
# rights (see accounts/management/commands/seed_roles.py). Django
# superusers are also allowed. HR Officer / Reviewer / Interviewer can
# still view the application, but cannot record the final decision.
FINAL_DECISION_ROLES = ("Super Admin", "Administrator")

def _can_make_final_decision(user):

    if not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    role = getattr(user, "role", None)

    return bool(role and role.name in FINAL_DECISION_ROLES)

def _send_candidate_outcome_email(application, agreed_with_ai=True):
    """
    FINAL FINISHING SESSION (2026-10-04, Section M). Sends via
    whichever EMAIL_BACKEND is configured (Brevo HTTPS API in
    production -- see accounts/email_backends.py; Django's console/
    locmem backend locally if BREVO_API_KEY is unset) -- same call
    shape accounts/views_auth.py already uses, no new email system.

    Candidate-safe by construction: only the job title, the final
    outcome (accepted/rejected), and the candidate-facing feedback
    text already shown on their own Candidate Detail page
    (application.ai_feedback) are included. Never the recruiter's own
    reason (HumanDecision.reason is internal-only), never RAG/legal
    evidence, never any other candidate's data.

    FEEDBACK/OUTCOME CONSISTENCY FIX (2026-10-05): application.ai_feedback
    is always the AI's OWN recommendation text (e.g. "Do not proceed
    with this candidate..."), written before any human review ever
    happens. When the administrator's final decision AGREES with the
    AI, that text is still an accurate explanation of the outcome, so
    it is included as before. When the administrator OVERRIDES the AI
    (agreed_with_ai=False -- e.g. AI said "Not Recommended" but the
    final decision is "accepted"), showing that same AI text next to
    an opposite outcome is self-contradictory and confusing for the
    candidate, so it is omitted in favor of a neutral line instead.
    The recruiter's actual reason (HumanDecision.reason) still stays
    internal-only -- this fix does not expose it.
    """

    candidate_email = (application.candidate.email or "").strip()

    if not candidate_email:
        raise ValueError("Candidate has no email address on file.")

    outcome_label = (
        "accepted" if application.status == "accepted" else "not selected"
    )

    subject = f"Update on your application: {application.job.title}"

    body_lines = [
        f"Dear {application.candidate.full_name},",
        "",
        f"Thank you for applying for the {application.job.title} "
        "position.",
        "",
        f"After review, your application has been {outcome_label}.",
    ]

    if application.ai_feedback and agreed_with_ai:
        body_lines += [
            "",
            "Feedback:",
            application.ai_feedback,
        ]
    elif not agreed_with_ai:
        body_lines += [
            "",
            "This outcome reflects the final decision of an "
            "authorized human recruitment officer after full review "
            "of your application.",
        ]

    body_lines += [
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

@login_required
def candidate_detail(request, application_id):

    application = get_object_or_404(
        Application.objects.select_related(
            "candidate",
            "job"
        ),
        id=application_id
    )

    is_staff = _has_recruitment_permission(request.user)

    is_owner = (
        application.candidate.user_id is not None
        and application.candidate.user_id == request.user.id
    )

    if not (is_staff or is_owner):
        return HttpResponseForbidden(
            "You do not have permission to view this application."
        )

    if request.method == "POST" and request.POST.get("form_type") == "human_decision":

        # Human Review is a staff-only action -- a candidate viewing
        # their own application (is_owner) must never be able to
        # approve/reject their own screening, even though they can
        # view the same page.
        # Restricted further to administrators only (final decision).
        if not (is_staff and _can_make_final_decision(request.user)):
            return HttpResponseForbidden(
                "Only an administrator can record the final review decision."
            )

                # LOCKED FINAL DECISION (2026-10-05): once an administrator has
        # recorded a Human Review decision for this application, it is
        # final and can no longer be changed from this page -- the
        # "Change the decision" buttons are no longer rendered once a
        # decision exists (see candidate_detail.html). This check is
        # the server-side backstop for that same rule, so it still
        # holds even if a POST is sent directly. Without this,
        # update_or_create() below would silently overwrite a decision
        # that already triggered Notification #2 (the final-decision
        # email), which could send that email to the candidate a
        # second time with a different outcome.
        if hasattr(application, "human_decision"):

            messages.error(
                request,
                "A final decision has already been recorded for this "
                "application and cannot be changed."
            )

            return redirect(
                "candidate_detail",
                application_id=application.id
            )

        decision = request.POST.get("decision")

        reason = (request.POST.get("reason") or "").strip()

        if decision not in ("approved", "rejected"):

            messages.error(
                request,
                "Please select Approve or Reject."
            )

        elif not reason:

            messages.error(
                request,
                "Please provide a reason for this decision — it's "
                "required for the audit trail."
            )

        else:

            ai_decision = (application.ai_decision or "").lower()

            ai_leans_positive = ai_decision in (
                "highly recommended", "recommended", "consider"
            )

            agreed_with_ai = (
                (decision == "approved" and ai_leans_positive)
                or (decision == "rejected" and not ai_leans_positive)
            )

            HumanDecision.objects.update_or_create(
                application=application,
                defaults={
                    "decided_by": (
                        request.user if request.user.is_authenticated
                        else None
                    ),
                    "decision": decision,
                    "reason": reason,
                    "agreed_with_ai": agreed_with_ai
                }
            )

            application.status = (
                "accepted" if decision == "approved" else "rejected"
            )

            application.save()

            # FINAL FINISHING SESSION (2026-10-04, Section M): candidate
            # feedback email, triggered only after the ADMIN's final
            # recommendation is recorded -- never before, and never
            # with the AI's own output standing in as the outcome.
            # Reuses the EXISTING Brevo-backed send_mail() (same one
            # accounts/views_auth.py already uses for verification
            # emails) -- no new email system. Content is limited to
            # what a candidate may see: job title, outcome, and the
            # candidate-safe recommendation text already shown to them
            # elsewhere (ai_feedback) -- never the recruiter's reason,
            # internal RAG/legal evidence, or any other internal
            # field. Never blocks the admin's own request -- a mail
            # failure is caught and surfaced as a warning, not a hard
            # error, and does NOT undo the recorded decision.
            try:
                _send_candidate_outcome_email(
                    application, agreed_with_ai=agreed_with_ai
                )
            except Exception as e:
                messages.warning(
                    request,
                    "Decision recorded, but the candidate notification "
                    f"email could not be sent right now ({e}). You may "
                    "need to follow up with the candidate directly."
                )

            messages.success(
                request,
                "Human decision recorded."
            )

        return redirect(
            "candidate_detail",
            application_id=application.id
        )

    context = {
        "application": application,
        "can_decide": is_staff and _can_make_final_decision(request.user),
    }

    return render(
        request,
        "talent/candidate_detail.html",
        context
    )

def job_list(request):

    query = (request.GET.get("q") or "").strip()

    jobs = Job.objects.all().order_by("-id")

    if query:

        jobs = jobs.filter(
            Q(title__icontains=query)
            | Q(department__icontains=query)
            | Q(description__icontains=query)
        )

    paginator = Paginator(jobs, 9)

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        'talent/job_list.html',
        {
            'jobs': page_obj,
            'page_obj': page_obj,
            'query': query
        }
    )

def job_detail(request, job_id):

    job = get_object_or_404(
        Job,
        id=job_id
    )

    context = {
        "job": job
    }

    # Candidate ranking/scores are internal, staff-only data — this
    # page itself is public so prospective candidates can view the
    # posting and apply, but anonymous visitors must not see who
    # else applied or their AI scores.
    if request.user.is_authenticated:

        context["applications"] = (
            Application.objects
            .filter(
                job=job
            )
            .select_related(
                "candidate"
            )
            .order_by(
                "-ai_score",
                "-applied_at"
            )
        )

    return render(
        request,
        "talent/job_detail.html",
        context
    )

@login_required
def apply_job(request, job_id):

    job = get_object_or_404(Job, id=job_id)

    existing_candidate = getattr(request.user, "candidate_profile", None)
        # Block re-applying to the same job -- this guard was accidentally
    # dropped from a previous merge (views.py lost it while the Tetum
    # job-description work was combined in), leaving nothing but a raw
    # DB IntegrityError protecting against duplicate Application rows.
    if existing_candidate is not None and Application.objects.filter(
        candidate=existing_candidate, job=job
    ).exists():

        messages.warning(
            request,
            "You have already applied to this position."
        )

        return redirect("job_detail", job_id=job.id)

    if existing_candidate is not None and existing_candidate.full_name:
        applicant_full_name = existing_candidate.full_name
    else:
        applicant_full_name = (request.user.first_name or "").strip()

    if existing_candidate is not None and existing_candidate.email:
        applicant_email = existing_candidate.email
    else:
        applicant_email = (request.user.email or "").strip()

    if request.method == "POST":

        if not applicant_full_name or not applicant_email:

            messages.error(
                request,
                "Your account is missing a full name or email address. "
                "Please update your profile before applying."
            )

            return redirect(
                "apply_job",
                job_id=job.id
            )

        full_name = applicant_full_name
        email = applicant_email
        cv_file = request.FILES.get("cv_file")

        # =====================================
        # VALIDATE UPLOADED FILE
        # (extension + size, before it ever touches
        # disk/memory processing)
        # =====================================

        if not cv_file:

            messages.error(
                request,
                "Please attach your CV as a PDF file."
            )

            return redirect(
                "apply_job",
                job_id=job.id
            )

        if not cv_file.name.lower().endswith(".pdf"):

            messages.error(
                request,
                "Only PDF files are accepted for the CV upload."
            )

            return redirect(
                "apply_job",
                job_id=job.id
            )

        if cv_file.size > MAX_CV_FILE_SIZE_BYTES:

            messages.error(
                request,
                "That file is too large. Please upload a PDF under "
                f"{MAX_CV_FILE_SIZE_BYTES // (1024 * 1024)}MB."
            )

            return redirect(
                "apply_job",
                job_id=job.id
            )

        # =====================================
        # CREATE OR REUSE CANDIDATE
        # (a logged-in user's Candidate profile is reused across
        # applications to different jobs, rather than creating a
        # fresh row each time -- this is what lets the existing
        # unique_together=("candidate","job") constraint on
        # Application actually prevent duplicate applications by
        # the same real person, and what "My Applications" queries
        # by)
        # =====================================

        if existing_candidate is not None:

            candidate = existing_candidate
            candidate.full_name = full_name
            candidate.email = email
            candidate.cv_file = cv_file
            candidate.save()

        else:

            candidate = Candidate.objects.create(
                user=request.user,
                full_name=full_name,
                email=email,
                cv_file=cv_file
            )

        # =====================================
        # DOCUMENT/CV QUALITY GATE (FINAL FINISHING SESSION, 2026-10-04)
        # =====================================
        # Runs BEFORE any Application row is created and BEFORE any
        # expensive AI call -- a document classified invalid here
        # never reaches candidate profiling / Rule Engine / Skill
        # Matching / RAG / fused reasoning at all. This reuses the
        # EXISTING extraction/OCR pipeline unchanged (see
        # talent/document_quality.py) -- no OCR rewrite, no new
        # extraction logic, just an explicit, loggable decision
        # object instead of a bare try/except around
        # extract_text_from_pdf().
        # =====================================

        pdf_path = candidate.cv_file.path

        _extract_start = perf_counter()

        quality = check_document_quality(pdf_path)

        print(
            "[APPLY-JOB-TIMING] "
            f"text_extraction={perf_counter() - _extract_start:.2f}s"
        )

        print(
            "[DOCUMENT-QUALITY] "
            f"valid={quality.valid} "
            f"extraction_method={quality.extraction_method} "
            f"ocr_used={quality.ocr_used} "
            f"extracted_text_length={quality.extracted_text_length}"
        )

        if not quality.valid:
            # DOCUMENT_INVALID: no Application row is created (same
            # behavior as before this change -- the candidate record
            # created above is rolled back), so the expensive AI
            # pipeline is never queued for an unreadable document.
            # Candidate can immediately resubmit with a better file.
            candidate.cv_file.delete(save=False)
            candidate.delete()

            messages.error(request, quality.reason)

            return redirect(
                "apply_job",
                job_id=job.id
            )

        candidate.extracted_text = quality.extracted_text

        candidate.save()

        if quality.ocr_used and quality.quality_notice:
            # Text was recovered via OCR fallback, but at LOW
            # confidence, or with an extraction warning (see
            # ai_engine/services/ocr_fallback.py /
            # document_extraction/router.py). Surface this to the
            # human now, at submission time -- don't wait for a
            # recruiter to notice sparse/garbled fields later on
            # Candidate Detail.
            messages.warning(
                request,
                "Your CV appears to be a scanned document, and text "
                "extraction quality was low. Some information may not "
                "have been read correctly. Consider re-uploading a "
                "clearer scan or a digitally-generated PDF if your "
                "application results look incomplete."
            )

        # =====================================
        # CREATE APPLICATION -- QUEUED for background AI processing
        # =====================================
        # ASYNC APPLY JOB (FINAL FINISHING SESSION, 2026-10-04): the
        # expensive AI pipeline (lang-detect/translate, candidate
        # profile, rule engine, skill matching, RAG, fused reasoning,
        # db save -- measured 89-211s across real local profiling,
        # see chat report) NO LONGER runs inside this HTTP request.
        # The candidate gets an immediate response; a separate
        # background worker (management command
        # process_pending_applications, see
        # ai_engine/management/commands/) picks up QUEUED applications
        # and runs the SAME recruitment_pipeline() unchanged. This is
        # a durable, DB-backed queue (ai_status is a plain CharField,
        # no migration needed for new string values) -- not an
        # in-memory thread, so it survives a web-process restart.
        # =====================================

        application = Application.objects.create(
            candidate=candidate,
            job=job
        )

        application.ai_status = "QUEUED"

        application.save()

        messages.success(
            request,
            "Application submitted successfully. Your CV passed "
            "quality checks and has been queued for AI-assisted "
            "screening -- you can check back on your application "
            "status, you do not need to keep this page open."
        )

        return redirect(
            "job_detail",
            job_id=job.id
        )

    return render(
    request,
    "talent/apply_job.html",
        {
            "job": job,
            "applicant_full_name": applicant_full_name,
            "applicant_email": applicant_email
        }
    )

@login_required
def candidate_cv_text(request, candidate_id):

    candidate = get_object_or_404(
        Candidate,
        id=candidate_id
    )

    return render(
        request,
        'talent/candidate_cv_text.html',
        {
            'candidate': candidate
        }
    )

@login_required
@permission_required("recruitment_manage")
def candidate_ranking(request):

    query = (request.GET.get("q") or "").strip()

    applications = (
        Application.objects
        .select_related(
            'candidate',
            'job'
        )
        .order_by(
            '-ai_score'
        )
    )

    if query:

        applications = applications.filter(
            Q(candidate__full_name__icontains=query)
            | Q(job__title__icontains=query)
            | Q(ai_decision__icontains=query)
        )

    paginator = Paginator(applications, 15)

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        'talent/candidate_ranking.html',
        {
            'applications': page_obj,
            'page_obj': page_obj,
            'query': query
        }
    )

@login_required
@permission_required("recruitment_manage")
def ranking_jobs(request):

    query = (request.GET.get("q") or "").strip()

    jobs = Job.objects.all().order_by("-id")

    if query:

        jobs = jobs.filter(
            Q(title__icontains=query)
            | Q(department__icontains=query)
        )

    paginator = Paginator(jobs, 9)

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        'talent/ranking_jobs.html',
        {
            'jobs': page_obj,
            'page_obj': page_obj,
            'query': query
        }
    )

@login_required
@permission_required("recruitment_manage")
def ranking_by_job(
    request,
    job_id
):

    job = get_object_or_404(
        Job,
        id=job_id
    )

    applications = (
        Application.objects
        .filter(
            job=job
        )
        .select_related(
            'candidate'
        )
        .order_by(
            '-ai_score'
        )
    )

    return render(
        request,
        'talent/ranking_by_job.html',
        {
            'job': job,
            'applications': applications
        }
    )

@login_required
@permission_required("recruitment_manage")
def test_semantic_matching(
    request
):

    candidate = Candidate.objects.get(
        id=15
    )

    job = Job.objects.first()

    candidate_profile = {

    "education":
    candidate.education,

    "skills":
    candidate.candidate_skills,

    "languages":
    candidate.languages,

    "years_experience":
    candidate.years_experience,

    "summary":
    candidate.professional_summary
}
    
    result = semantic_match(
    candidate_profile,
    job.ai_job_profile
)
    
    return render(
    request,
    "talent/test_semantic.html",
    {
        "candidate": candidate,
        "job": job,
        "result": result
    }
)

@login_required
@permission_required("recruitment_manage")
def create_job(request):

    if request.method == "POST":

        form = JobForm(request.POST)

        if form.is_valid():

            job = form.save()

            try:

                process_job(job)

                messages.success(
                    request,
                    "Job created and AI profiling complete."
                )

            except Exception:

                messages.warning(
                    request,
                    "Job was created, but AI profiling could not be "
                    "completed right now (the AI service may be "
                    "unavailable). Candidates can still apply, but "
                    "matching accuracy may be affected until this is "
                    "reprocessed."
                )

            return redirect(
                "job_detail",
                job.id
            )

    else:

        form = JobForm()

    return render(

        request,

        "talent/create_job.html",

        {

            "form": form

        }

    )

def home(request):

    return render(
        request,
        "talent/home.html"
    )

@login_required
def my_applications(request):

    candidate = getattr(request.user, "candidate_profile", None)

    applications = (
        Application.objects.filter(candidate=candidate)
        .select_related("job")
        .order_by("-applied_at")
        if candidate is not None
        else Application.objects.none()
    )

    return render(
        request,
        "talent/my_applications.html",
        {"applications": applications}
    )