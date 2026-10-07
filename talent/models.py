from django.db import models
from django.conf import settings
import uuid

class Skill(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.name


class Job(models.Model):
    title = models.CharField(
        max_length=255
    )

    department = models.CharField(
        max_length=255
    )

    description = models.TextField()

    requirements = models.TextField()

    skills = models.ManyToManyField(
        Skill,
        blank=True
    )
    ai_job_profile = models.JSONField(
    blank=True,
        null=True
    )

    ai_rag_context = models.JSONField(
        default=dict,
        blank=True
    )

    ai_processed = models.BooleanField(
        default=False
    )

    ai_processing_time = models.FloatField(
        default=0
    )

    ai_processed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.title


class Candidate(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidate_profile"
    )

    full_name = models.CharField(
        max_length=255
    )

    email = models.EmailField(
        unique=True
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
        null=True
    )

    address = models.TextField(
        blank=True,
        null=True
    )

    education = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    years_experience = models.PositiveIntegerField(
        default=0
    )

    cv_file = models.FileField(
        upload_to='cv/'
    )

    extracted_text = models.TextField(
        blank=True,
        null=True
    )

    skills = models.ManyToManyField(
        Skill,
        blank=True
    )

    candidate_skills = models.TextField(
        blank=True,
        null=True
    )

    languages = models.TextField(
    blank=True,
    null=True
    )

    certifications = models.TextField(
        blank=True,
        null=True
    )
    
  
    professional_summary = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.full_name


class Application(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("screening", "Screening"),
        ("shortlisted", "Shortlisted"),
        ("interview", "Interview"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    ]

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="applications"
    )

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name="applications"
    )

    # =====================================================
    # AI SUMMARY
    # =====================================================

    ai_score = models.FloatField(
        default=0
    )

    ai_decision = models.CharField(
        max_length=50,
        blank=True,
        default=""
    )

    ai_confidence = models.FloatField(
        default=0
    )

    ai_feedback = models.TextField(
        blank=True,
        default=""
    )

    # =====================================================
    # AI PIPELINE OUTPUT
    # =====================================================

    ai_profile = models.JSONField(
        default=dict,
        blank=True
    )

    ai_job_profile = models.JSONField(
        default=dict,
        blank=True
    )

    ai_rule_result = models.JSONField(
        default=dict,
        blank=True
    )

    ai_semantic_result = models.JSONField(
        default=dict,
        blank=True
    )

    ai_skill_gap = models.JSONField(
        default=dict,
        blank=True
    )

    ai_rag_context = models.JSONField(
        default=dict,
        blank=True
    )

    ai_explainable_report = models.JSONField(
        default=dict,
        blank=True
    )

    # =====================================================
    # AI MONITORING
    # =====================================================

    ai_model = models.CharField(
        max_length=100,
        default="gemma3:12b"
    )

    ai_provider = models.CharField(
        max_length=50,
        default="Ollama (local)"
    )

    ai_version = models.CharField(
        max_length=30,
        default="1.0.0"
    )

    ai_processing_time = models.FloatField(
        default=0
    )

    ai_status = models.CharField(
        max_length=30,
        default="SUCCESS"
    )

    ai_error = models.TextField(
        blank=True,
        default=""
    )

    ai_processed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # TASK I: ai_status now also carries EXTRACTING, EXTRACTED,
    # DOCUMENT_INVALID and EXTRACTION_FAILED (plain strings, no
    # choices= on the field, so no migration is needed for the values
    # themselves). See talent/statuses.py for the full state machine.

    # TASK I: what the document-extraction stage actually did for this
    # application (per-page methods, failed/unreadable pages, DPI,
    # timings, warnings). Filled by the worker; {} until then.
    extraction_report = models.JSONField(
        default=dict,
        blank=True
    )

    # =====================================================
    # APPLICATION STATUS
    # =====================================================

    status = models.CharField(
        max_length=50,
        choices=STATUS_CHOICES,
        default="pending"
    )

    applied_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        unique_together = ("candidate", "job")

    def __str__(self):
        return f"{self.candidate.full_name} - {self.job.title}"


class ApplicationDocument(models.Model):
    """
    TASK I: the uploaded CV PDF, carried to the background worker
    through the database.

    WHY THE DATABASE: the web service and the worker service are
    separate Railway containers with separate filesystems (MEDIA_ROOT
    is local disk), so the worker cannot open the file the web process
    saved. The bytes travel in this row instead.

    WHY A SEPARATE TABLE (not a field on Application): Application is
    loaded by every list/ranking query; a BinaryField there would drag
    up to 5MB per row into each of them.

    Lifetime: created by apply_job(), kept while the application is
    in flight (so a worker crash can be retried from the start), and
    deleted once the application reaches a terminal state (SUCCESS,
    FAILED, DOCUMENT_INVALID, EXTRACTION_FAILED). Applications queued
    before this table existed simply have no row -- the worker treats
    that as "text already extracted" (legacy path).
    """

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="pending_document"
    )

    pdf_bytes = models.BinaryField()

    original_filename = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    sha256 = models.CharField(
        max_length=64,
        blank=True,
        default=""
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"Document for application {self.application_id}"


class HumanDecision(models.Model):
    """
    Phase 15 — Human-in-the-Loop Review.

    Records the recruiter's final call SEPARATELY from the AI's
    recommendation (application.ai_decision), so agreement/override
    can be measured, and so a reason is always captured. This is
    also the intended seed for a future human-validated dataset
    (see docs/PAPER_FRAMEWORK.md future-work notes) — never used
    to auto-train anything today, just recorded.

    One decision per application: re-submitting overwrites the
    previous record rather than creating a history, since only the
    final human call matters for the recruitment record itself.
    """

    DECISION_CHOICES = [
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="human_decision"
    )

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    decision = models.CharField(
        max_length=20,
        choices=DECISION_CHOICES
    )

    reason = models.TextField()

    agreed_with_ai = models.BooleanField(
        default=False,
        help_text=(
            "True if this decision's direction (approved/rejected) "
            "matches the AI's recommendation category at the time "
            "of this decision."
        )
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.application} -> {self.decision}"