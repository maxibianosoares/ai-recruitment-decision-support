from django.contrib import admin
from .models import (
    User,
    Role,
    Permission,
    Department,
    Position,
    EmailLog,
)

admin.site.register(User)
admin.site.register(Department)
admin.site.register(Role)
admin.site.register(Permission)
admin.site.register(Position)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    """Read-only delivery log (TASK M): nobody should edit history."""

    list_display = (
        "created_at", "status", "kind", "recipient",
        "attempts", "related_application_id",
    )
    list_filter = ("status", "kind")
    search_fields = ("recipient", "subject", "error")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
