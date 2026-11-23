"""
Database models for the NFC plugin in InvenTree.

Defines NFCTagLink: a many-to-one relationship between NFC tag UIDs and
InvenTree StockItems (each StockItem = one physical tube). A Part (e.g.
"Mix A") has many StockItems (tubes); each tube carries exactly one NFC tag.
The tag identifies the specific tube, so a scan is unambiguous about which
lot/expiry/quantity the user is holding.

Defines NFCEvent: the plugin-owned history of every NFC action performed on
a unit, independent from InvenTree's own stock history implementation.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


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
        related_name="nfc_links_created",
    )

    # Recorded when the link is deactivated (unlinked), for history.
    unlinked_at = models.DateTimeField(null=True, blank=True)
    unlinked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nfc_links_removed",
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


class NFCEvent(models.Model):
    """One entry of a unit's NFC history (creation, stock change, consumption, tag link/unlink)."""

    KIND_CREATED = "created"
    KIND_STOCK = "stock"
    KIND_CONSUMED = "consumed"
    KIND_LINK = "link"
    KIND_UNLINK = "unlink"

    KIND_CHOICES = (
        (KIND_CREATED, "Unit created"),
        (KIND_STOCK, "Stock change"),
        (KIND_CONSUMED, "Unit consumed"),
        (KIND_LINK, "Tag linked"),
        (KIND_UNLINK, "Tag unlinked"),
    )

    stock_item = models.ForeignKey(
        "stock.StockItem",
        on_delete=models.CASCADE,
        related_name="nfc_events",
        verbose_name="Stock Item",
    )

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nfc_events",
    )

    date = models.DateTimeField(default=timezone.now, db_index=True)

    quantity = models.DecimalField(
        max_digits=15, decimal_places=5, null=True, blank=True
    )

    delta = models.DecimalField(max_digits=15, decimal_places=5, null=True, blank=True)

    uid = models.CharField(max_length=64, blank=True, default="")

    notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "nfc"
        ordering = ["-date", "-pk"]
        indexes = [
            models.Index(fields=["stock_item", "date"], name="nfc_event_item_date"),
        ]

    def __str__(self):
        return f"NFC {self.kind} : stock #{self.stock_item_id} @ {self.date:%Y-%m-%d %H:%M}"


def record_event(
    stock_item, kind, user, *, quantity=None, delta=None, uid="", notes="", date=None
):
    """Record an NFC history event for a unit.

    Must be called inside the same transaction as the action it describes, so
    that a failure to record the event rolls back the action itself.

    Args:
        stock_item: The StockItem the event applies to.
        kind: One of the NFCEvent.KIND_* values.
        user: The user performing the action (None for unknown).
        quantity: Resulting quantity of the unit after the action.
        delta: Signed quantity change caused by the action.
        uid: NFC tag UID involved in the action, if any.
        notes: Free text notes.
        date: Event date; defaults to now.

    Returns:
        The created NFCEvent.

    Raises:
        ValueError: If kind is not a known event kind.
    """
    if kind not in dict(NFCEvent.KIND_CHOICES):
        raise ValueError(f"Unknown NFC event kind: {kind!r}")

    if user is not None and not getattr(user, "is_authenticated", True):
        user = None

    return NFCEvent.objects.create(
        stock_item=stock_item,
        kind=kind,
        user=user,
        date=date or timezone.now(),
        quantity=quantity,
        delta=delta,
        uid=(uid or "").strip().upper(),
        notes=notes or "",
    )
