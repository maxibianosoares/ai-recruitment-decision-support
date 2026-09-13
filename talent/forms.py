from django import forms

from .models import Job


class JobForm(forms.ModelForm):

    class Meta:

        model = Job

        fields = [
            "title",
            "department",
            "description",
            "requirements",
            "skills",
        ]

        widgets = {

            "description": forms.Textarea(
                attrs={"rows":6}
            ),

            "requirements": forms.Textarea(
                attrs={"rows":6}
            ),

            "skills": forms.CheckboxSelectMultiple()

        }