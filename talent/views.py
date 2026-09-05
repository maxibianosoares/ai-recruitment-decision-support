from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Job
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
    Application
)
from .utils import extract_text_from_pdf, CVExtractionError

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

@login_required
def candidate_detail(request, application_id):

    application = get_object_or_404(
        Application.objects.select_related(
            "candidate",
            "job"
        ),
        id=application_id
    )

    context = {
        "application": application,
    }

    return render(
        request,
        "talent/candidate_detail.html",
        context
    )

def job_list(request):

    jobs = Job.objects.all()

    return render(
        request,
        'talent/job_list.html',
        {
            'jobs': jobs
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

def apply_job(request, job_id):

    job = get_object_or_404(Job, id=job_id)

    if request.method == "POST":

        full_name = request.POST.get("full_name")
        email = request.POST.get("email")
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
        # CREATE CANDIDATE
        # =====================================

        candidate = Candidate.objects.create(
            full_name=full_name,
            email=email,
            cv_file=cv_file
        )

        # =====================================
        # EXTRACT PDF TEXT
        # =====================================

        try:

            pdf_path = candidate.cv_file.path

            candidate.extracted_text = extract_text_from_pdf(pdf_path)

            candidate.save()

        except CVExtractionError as e:

            candidate.cv_file.delete(save=False)
            candidate.delete()

            messages.error(request, str(e))

            return redirect(
                "apply_job",
                job_id=job.id
            )

        # =====================================
        # CREATE APPLICATION
        # =====================================

        application = Application.objects.create(
            candidate=candidate,
            job=job
        )

        # =====================================
        # RUN AI PIPELINE
        # =====================================

        try:
            recruitment_pipeline(application)
            messages.success(
                request,
                "Application submitted and AI analysis complete."
            )

        except Exception:
            # recruitment_pipeline already recorded ai_status="FAILED"
            # and the error detail on the application before re-raising.
            # The application/candidate stay saved so a recruiter can
            # still see it and re-run analysis later; we just avoid
            # crashing the candidate's browser mid-submission.
            messages.error(
                request,
                "Your application was submitted, but the AI analysis "
                "could not be completed right now (the AI service may "
                "be unavailable). A recruiter will review it manually."
            )

        return redirect(
            "job_detail",
            job_id=job.id
        )

    return render(
        request,
        "talent/apply_job.html",
        {
            "job": job
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
def candidate_ranking(request):

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

    return render(
        request,
        'talent/candidate_ranking.html',
        {
            'applications': applications
        }
    )

@login_required
def ranking_jobs(request):

    jobs = Job.objects.all()

    return render(
        request,
        'talent/ranking_jobs.html',
        {
            'jobs': jobs
        }
    )


@login_required
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