"""
Database models for the NFC plugin in InvenTree.

Defines NFCTagLink: a many-to-one relationship between NFC tag UIDs and
InvenTree StockItems (each StockItem = one physical tube). A Part (e.g.
"Mix A") has many StockItems (tubes); each tube carries exactly one NFC tag.
The tag identifies the specific tube, so a scan is unambiguous about which
lot/expiry/quantity the user is holding.
"""

from django.conf import settings
from django.db import models


class NFCTagLink(models.Model):
    """Maps an NFC tag UID to a specific StockItem (a tube)."""

    uid = models.CharField(max_length=64, verbose_name="NFC Tag UID")

    stock_item = models.ForeignKey(
        "stock.StockItem",
        on_delete=models.CASCADE,
        related_name="nfc_tags",
        verbose_name="Linked Stock Item",
    )

    active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        app_label = "nfc"
        ordering = ["-linked_at"]
        constraints = [
            # One physical UID can have only one active link at a time.
            models.UniqueConstraint(
                fields=["uid"],
                condition=models.Q(active=True),
                name="unique_active_uid",
            ),
            # One tube can have only one active tag at a time.
            # (A Part still has many tubes -> many tags, which is what we want.)
            models.UniqueConstraint(
                fields=["stock_item"],
                condition=models.Q(active=True),
                name="unique_active_stock_item",
            ),
        ]

    def save(self, *args, **kwargs):
        self.uid = (self.uid or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"NFC {self.uid} : stock #{self.stock_item_id}"