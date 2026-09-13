from django.db import models

# Create your models here.
class JobPosition(models.Model):
    title = models.CharField(max_length=255)
    department = models.CharField(max_length=255)
    description = models.TextField()

    def __str__(self):
        return self.title
    

class CandidateResult(models.Model):

    candidate_name = models.CharField(
        max_length=200
    )

    final_score = models.FloatField(
        default=0
    )

    decision = models.CharField(
        max_length=50
    )

    confidence = models.FloatField(
        default=0
    )

    semantic_score = models.FloatField(
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    ai_result = models.JSONField(
        default=dict
    )

    def __str__(self):
        return self.candidate_name