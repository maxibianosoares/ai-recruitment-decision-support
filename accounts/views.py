from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.shortcuts import render
from django.shortcuts import redirect

from .forms import UserForm
from .models import User
from .decorators import permission_required

from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout

from django.shortcuts import (
    get_object_or_404
)

from talent.models import Application

@login_required
def logout_view(request):

    logout(request)

    return redirect('login')

def login_view(request):

    if request.method == 'POST':

        username = request.POST.get('username')

        password = request.POST.get('password')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user:

            if not user.is_verified:
                return render(
                    request,
                    'accounts/login.html',
                    {
                        'error': (
                            'Please verify your email address before '
                            'logging in.'
                        )
                    }
                )

            login(request, user)
            return redirect('dashboard')

        return render(
            request,
            'accounts/login.html',
            {'error': 'Invalid username or password.'}
        )

    return render(
        request,
        'accounts/login.html'
    )


@login_required
def dashboard(request):

    # 2026-09-27: this view previously rendered dashboard.html with no
    # context at all, so its stat tiles (Total Candidates, Highly
    # Recommended, Recommended, Not Recommended) and the candidate
    # table always rendered empty -- there is a separate,
    # never-actually-used dashboard() in recruitment/views.py that
    # already had the right aggregation shape, but it queried
    # recruitment.CandidateResult, a model nothing in the AI pipeline
    # ever writes to (confirmed: no .save()/.create() anywhere in the
    # codebase). The real, live data the pipeline actually writes is
    # on talent.Application (ai_score/ai_decision/ai_status, see
    # ai_engine/services/recruitment_pipeline.py). Only applications
    # the pipeline finished successfully (ai_status="SUCCESS") are
    # counted, so an application still pending or one that hit a
    # technical failure (ai_decision left blank) does not skew the
    # decision breakdown.
    applications = Application.objects.filter(
        ai_status="SUCCESS"
    ).select_related("candidate", "job").order_by("-ai_score")

    total = applications.count()

    highly = applications.filter(
        ai_decision="Highly Recommended"
    ).count()

    recommended = applications.filter(
        ai_decision="Recommended"
    ).count()

    consider = applications.filter(
        ai_decision="Consider"
    ).count()

    not_recommended = applications.filter(
        ai_decision="Not Recommended"
    ).count()

    candidates = [
        {
            "candidate_name": application.candidate.full_name,
            "final_score": application.ai_score,
            "decision": application.ai_decision,
        }
        for application in applications
    ]

    context = {
        "total": total,
        "highly": highly,
        "recommended": recommended,
        "consider": consider,
        "not_recommended": not_recommended,
        "candidates": candidates,
    }

    return render(
        request,
        'dashboard.html',
        context
    )



@login_required
@permission_required(
    "user_view"
)
def user_list(request): 

    users = User.objects.all().order_by("username")

    return render(

        request,

        "accounts/user_list.html",

        {

            "users": users

        }

    )


@login_required
@permission_required(
    "user_view"
)
def user_detail(

    request,

    user_id

):

    user = get_object_or_404(

        User,

        id=user_id

    )

    return render(

        request,

        "accounts/user_detail.html",

        {

            "user_obj": user

        }

    )


@permission_required(
    "user_create"
)
@login_required

def user_create(request):

    if request.method == "POST":

        form = UserForm(request.POST, request.FILES)

        if form.is_valid():

            form.save()

            return redirect("user_list")

    else:

        form = UserForm()

    return render(

        request,

        "accounts/user_form.html",

        {

            "form": form,

            "title": "Create User"

        }

    )


@login_required

@permission_required(
    "user_edit"
)


def user_edit(

    request,

    user_id

):

    user = get_object_or_404(

        User,

        id=user_id

    )

    if request.method == "POST":

        form = UserForm(

            request.POST,

            request.FILES,

            instance=user

        )

        if form.is_valid():

            form.save()

            return redirect("user_list")

    else:

        form = UserForm(

            instance=user

        )

    return render(

        request,

        "accounts/user_form.html",

        {

            "form": form,

            "title": "Edit User"

        }

    )


@login_required

@permission_required(
    "user_delete"
)
def user_delete(

    request,

    user_id

):

    user = get_object_or_404(

        User,

        id=user_id

    )

    if request.method == "POST":

        user.delete()

        return redirect("user_list")

    return render(

        request,

        "accounts/user_delete.html",

        {

            "user_obj": user

        }

    )


@login_required

def profile(request):

    return render(

        request,

        "accounts/profile.html",

        {

            "user_obj": request.user

        }

    )