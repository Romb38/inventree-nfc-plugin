"""Admin site configuration for the NFC plugin."""

from django.contrib import admin

from .models import NFCEvent, NFCTagLink


@admin.register(NFCTagLink)
class NFCTagLinkAdmin(admin.ModelAdmin):
    """Admin interface for the NFCTagLink"""

    list_display = ("uid", "stock_item", "linked_at", "linked_by")

    list_filter = ("uid",)

    search_fields = ("uid", "stock_item__part__name")


@admin.register(NFCEvent)
class NFCEventAdmin(admin.ModelAdmin):
    """Read-only admin interface for the NFC history (NFCEvent)."""

    list_display = ("date", "kind", "stock_item", "user", "delta", "quantity", "uid")

    list_filter = ("kind",)

    search_fields = ("uid", "stock_item__part__name", "user__username")

    def has_add_permission(self, request):
        """History entries are only created by the plugin."""
        return False

    def has_change_permission(self, request, obj=None):
        """History entries are immutable."""
        return False
