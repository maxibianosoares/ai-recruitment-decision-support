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