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

        # F-04 (Phase 28): {{ form.as_p }} in create_job.html was
        # rendering every field with Django's default (unstyled)
        # widget -- Textarea's default cols="40" is wider than a
        # mobile viewport and, unlike the rest of the app (see
        # apply_job.html), nothing here had Bootstrap's form-control
        # class, so fields didn't resize with the page. Adding the
        # same classes apply_job.html already uses is presentation
        # only: field list, model, validation and save() behavior
        # are unchanged.
        widgets = {

            "title": forms.TextInput(
                attrs={"class": "form-control"}
            ),

            "department": forms.TextInput(
                attrs={"class": "form-control"}
            ),

            "description": forms.Textarea(
                attrs={"rows":6, "class": "form-control"}
            ),

            "requirements": forms.Textarea(
                attrs={"rows":6, "class": "form-control"}
            ),

            "skills": forms.CheckboxSelectMultiple(
                attrs={"class": "form-check-input"}
            )

        }