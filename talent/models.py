from django.db import models
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