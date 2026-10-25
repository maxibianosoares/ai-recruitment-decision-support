from django.contrib import admin
from .models import (
    Skill,
    Job,
    Candidate,
    Application,
    ApplicationSupportingDocument,
    ApplicationCvFile,
    HumanDecision
)

admin.site.register(Skill)
admin.site.register(Job)
admin.site.register(Candidate)
admin.site.register(Application)
admin.site.register(HumanDecision)
admin.site.register(ApplicationSupportingDocument)
admin.site.register(ApplicationCvFile)
