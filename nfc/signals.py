"""
Signal handlers for the NFC plugin.

InvenTree reloads plugin apps at runtime, which can leave the plugin models out
of the relation tree Django uses to cascade deletions. When that happens,
deleting a StockItem does not delete its NFC rows and the database rejects the
deletion with a foreign key violation. These handlers remove the plugin rows
explicitly, independently of the state of the app registry.
"""

from django.db.models.signals import pre_delete

DISPATCH_UID = "nfc_stock_item_pre_delete"


def delete_nfc_rows_for_stock_item(sender, instance, **kwargs):
    """Delete the NFC tag links and NFC events of a StockItem about to be deleted.

    Args:
        sender: The StockItem model class.
        instance: The StockItem being deleted.
        **kwargs: Extra signal arguments, unused.
    """
    from .models import NFCEvent, NFCTagLink

    if instance.pk is None:
        return

    NFCTagLink.objects.filter(stock_item_id=instance.pk).delete()
    NFCEvent.objects.filter(stock_item_id=instance.pk).delete()


def connect_signals():
    """Connect the NFC plugin signal handlers, once per process."""
    from stock.models import StockItem

    pre_delete.connect(
        delete_nfc_rows_for_stock_item,
        sender=StockItem,
        weak=False,
        dispatch_uid=DISPATCH_UID,
    )
