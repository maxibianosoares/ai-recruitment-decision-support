from django.contrib import admin
from .models import (
    User,
    Role,
    Permission,
    Department,
    Position
)

admin.site.register(User)
admin.site.register(Department)
admin.site.register(Role)
admin.site.register(Permission)
admin.site.register(Position)