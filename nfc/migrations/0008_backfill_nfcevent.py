"""
Backfill NFCEvent from the history that existed before InvenTree 1.7.

InvenTree 1.7 removed its legacy stock tracking model and copied its rows into the audit log
(stock.0129_migrate_stock_tracking_to_audit_log). The tracking deltas written by
the plugin are preserved in AuditLogEntry.additional_data["deltas"], and are
converted here into NFCEvent rows for every unit known to the plugin.

NFCTagLink (linked_at/by, unlinked_at/by) is used as a fallback source for tag
link and unlink events which have no audit log counterpart (e.g. tags linked
when a unit was created).
"""

import json
from decimal import Decimal, InvalidOperation

from django.db import migrations

ACTION_CREATE = 0

BATCH_SIZE = 500


def to_decimal(value):
    """Convert a stored delta value to a Decimal, or None if not numeric."""
    if value is None or isinstance(value, bool):
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def as_dict(value):
    """Return a JSON value as a dict (decoding strings), or an empty dict."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}

    return value if isinstance(value, dict) else {}


def convert_entry(entry):
    """Convert one AuditLogEntry into NFCEvent field values, or None if not an NFC event."""
    additional = as_dict(entry.additional_data)
    deltas = as_dict(additional.get("deltas"))

    base = {
        "stock_item_id": entry.object_id,
        "user_id": entry.actor_id,
        "date": entry.timestamp,
        "notes": entry.notes or "",
    }

    if deltas.get("nfc_link"):
        return {**base, "kind": "link", "uid": str(deltas["nfc_link"]).upper()}

    if deltas.get("nfc_unlink"):
        return {**base, "kind": "unlink", "uid": str(deltas["nfc_unlink"]).upper()}

    if deltas.get("created"):
        return {
            **base,
            "kind": "created",
            "quantity": to_decimal(deltas.get("quantity")),
        }

    if entry.action == ACTION_CREATE:
        quantity = as_dict(entry.changes).get("quantity")
        if isinstance(quantity, (list, tuple)) and len(quantity) == 2:
            quantity = quantity[1]
        return {**base, "kind": "created", "quantity": to_decimal(quantity)}

    added = to_decimal(deltas.get("added"))
    if added is not None:
        return {
            **base,
            "kind": "stock",
            "delta": added,
            "quantity": to_decimal(deltas.get("quantity")),
        }

    removed = to_decimal(deltas.get("removed"))
    if removed is not None:
        quantity = to_decimal(deltas.get("quantity"))
        return {
            **base,
            "kind": "consumed" if quantity == 0 else "stock",
            "delta": -removed,
            "quantity": quantity,
        }

    return None


def plugin_item_ids(apps):
    """Return the pks of every StockItem known to the plugin."""
    NFCTagLink = apps.get_model("nfc", "NFCTagLink")
    StockItem = apps.get_model("stock", "StockItem")

    ids = set(NFCTagLink.objects.values_list("stock_item_id", flat=True))
    ids.update(
        StockItem.objects.filter(metadata__has_key="container_type").values_list(
            "pk", flat=True
        )
    )
    return sorted(ids)


def backfill_from_audit_log(apps, item_ids):
    """Create NFCEvent rows from the audit log entries of the given units.

    Returns:
        A (created, ignored) tuple of counts.
    """
    NFCEvent = apps.get_model("nfc", "NFCEvent")
    AuditLogEntry = apps.get_model("audit", "AuditLogEntry")
    ContentType = apps.get_model("contenttypes", "ContentType")

    stock_ct = ContentType.objects.filter(app_label="stock", model="stockitem").first()
    if stock_ct is None:
        return 0, 0

    created = ignored = 0

    for start in range(0, len(item_ids), BATCH_SIZE):
        chunk = item_ids[start : start + BATCH_SIZE]
        entries = AuditLogEntry.objects.filter(
            content_type_id=stock_ct.pk, object_id__in=chunk
        ).order_by("timestamp", "pk")

        events = []
        for entry in entries.iterator():
            data = convert_entry(entry)
            if data is None:
                ignored += 1
                continue
            events.append(NFCEvent(**data))

        NFCEvent.objects.bulk_create(events, batch_size=BATCH_SIZE)
        created += len(events)

    return created, ignored


def backfill_from_tag_links(apps):
    """Create link/unlink NFCEvent rows from NFCTagLink when not already present.

    Returns:
        The number of events created.
    """
    NFCEvent = apps.get_model("nfc", "NFCEvent")
    NFCTagLink = apps.get_model("nfc", "NFCTagLink")

    known = set(
        NFCEvent.objects.filter(kind__in=("link", "unlink")).values_list(
            "stock_item_id", "kind", "uid"
        )
    )

    events = []
    for link in NFCTagLink.objects.order_by("linked_at", "pk").iterator():
        uid = (link.uid or "").upper()

        if (link.stock_item_id, "link", uid) not in known:
            events.append(
                NFCEvent(
                    stock_item_id=link.stock_item_id,
                    kind="link",
                    user_id=link.linked_by_id,
                    date=link.linked_at,
                    uid=uid,
                )
            )
            known.add((link.stock_item_id, "link", uid))

        if (
            not link.active
            and link.unlinked_at
            and (link.stock_item_id, "unlink", uid) not in known
        ):
            events.append(
                NFCEvent(
                    stock_item_id=link.stock_item_id,
                    kind="unlink",
                    user_id=link.unlinked_by_id,
                    date=link.unlinked_at,
                    uid=uid,
                )
            )
            known.add((link.stock_item_id, "unlink", uid))

    NFCEvent.objects.bulk_create(events, batch_size=BATCH_SIZE)
    return len(events)


def forward(apps, schema_editor):
    """Fill NFCEvent from the migrated audit log, then from NFCTagLink."""
    item_ids = plugin_item_ids(apps)
    created, ignored = backfill_from_audit_log(apps, item_ids)
    fallback = backfill_from_tag_links(apps)

    if created or ignored or fallback:
        print(
            f"\nnfc.migrations.0008: {created} events from audit log, "
            f"{ignored} audit entries ignored, {fallback} events from tag links"
        )


def reverse(apps, schema_editor):
    """Remove every backfilled (and later) NFC event."""
    apps.get_model("nfc", "NFCEvent").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nfc", "0007_nfcevent"),
        ("stock", "0130_delete_stockitemtracking"),
        ("audit", "0003_event_type"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(forward, reverse_code=reverse)]
