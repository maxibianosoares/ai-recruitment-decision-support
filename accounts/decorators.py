from functools import wraps
from .models import Role
from django.shortcuts import redirect


def permission_required(permission_code):

    def decorator(view_func):

        @wraps(view_func)

        def wrapper(request, *args, **kwargs):

            if not request.user.is_authenticated:

                return redirect("login")


            user = request.user


            role_id = user.role_id

            if role_id is None:
                return redirect("dashboard")

            has_permission = user.role.permissions.filter(
                code=permission_code
            ).exists()


            if not has_permission:

                return redirect("dashboard")


            return view_func(
                request,
                *args,
                **kwargs
            )


        return wrapper


    return decorator