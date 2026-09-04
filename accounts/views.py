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

    return render(
        request,
        'dashboard.html'
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
    "user_update"
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