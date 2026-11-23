"""
Tests for the NFCEvent backfill data migration (nfc.0008).

The migration functions are run against the live app registry, after seeding
AuditLogEntry rows shaped like the ones produced by InvenTree's
stock.0129_migrate_stock_tracking_to_audit_log from the plugin's legacy
stock tracking entries.
"""

import importlib
from datetime import timedelta
from decimal import Decimal

import pytest

backfill = importlib.import_module("nfc.migrations.0008_backfill_nfcevent")


@pytest.fixture()
def user(db, django_user_model):
    return django_user_model.objects.create_user(username="mig", password="pass")


@pytest.fixture()
def audit_entry(db):
    """Create an AuditLogEntry for a StockItem, as migrated by InvenTree 1.7."""
    from audit.models import AuditLogEntry
    from django.contrib.contenttypes.models import ContentType
    from django.utils import timezone

    stock_ct = ContentType.objects.get(app_label="stock", model="stockitem")

    def make(item, deltas=None, action=1, user=None, when=None, notes="", changes=None):
        additional = {"tracking_id": 1}
        if deltas is not None:
            additional["deltas"] = deltas
        return AuditLogEntry.objects.create(
            content_type=stock_ct,
            object_pk=str(item.pk),
            object_id=item.pk,
            object_repr=str(item.pk),
            action=action,
            changes=changes or {},
            timestamp=when or timezone.now(),
            actor=user,
            notes=notes or None,
            additional_data=additional,
        )

    return make


def _run():
    """Clear any NFCEvent and audit entries created as side effects, then run the backfill."""
    from django.apps import apps as registry

    from nfc.models import NFCEvent

    NFCEvent.objects.all().delete()
    backfill.forward(registry, None)
    return NFCEvent.objects.order_by("date", "pk")


def _clear_native_audit():
    """Remove audit entries InvenTree wrote while the fixtures were created."""
    from audit.models import AuditLogEntry

    AuditLogEntry.objects.all().delete()


@pytest.mark.django_db
def test_backfill_converts_plugin_entries(stock_item_factory, audit_entry, user):
    """created/added/nfc_link/nfc_unlink/removed entries become NFC events."""
    from django.utils import timezone

    item = stock_item_factory(quantity=10, metadata={"container_type": "Poche"})
    _clear_native_audit()
    t0 = timezone.now() - timedelta(days=10)

    audit_entry(item, {"quantity": 10.0, "created": True}, user=user, when=t0)
    audit_entry(
        item, {"quantity": 15.0, "added": 5.0}, user=user, when=t0 + timedelta(days=1)
    )
    audit_entry(item, {"nfc_link": "aabb"}, user=user, when=t0 + timedelta(days=2))
    audit_entry(
        item, {"quantity": 12.0, "removed": 3.0}, user=user, when=t0 + timedelta(days=3)
    )
    audit_entry(
        item, {"quantity": 0.0, "removed": 12.0}, user=user, when=t0 + timedelta(days=4)
    )
    audit_entry(item, {"nfc_unlink": "AABB"}, user=user, when=t0 + timedelta(days=5))

    events = list(_run())

    assert [e.kind for e in events] == [
        "created",
        "stock",
        "link",
        "stock",
        "consumed",
        "unlink",
    ]
    assert all(e.user_id == user.pk for e in events)
    assert events[0].date == t0
    assert events[0].quantity == Decimal("10")
    assert events[1].delta == Decimal("5")
    assert events[2].uid == "AABB"
    assert events[3].delta == Decimal("-3")
    assert events[4].quantity == Decimal("0")
    assert events[4].delta == Decimal("-12")


@pytest.mark.django_db
def test_backfill_native_creation(stock_item_factory, audit_entry, user):
    """A native InvenTree creation entry (action CREATE) becomes a 'created' event."""
    item = stock_item_factory(quantity=4, metadata={"container_type": "Poche"})
    _clear_native_audit()
    audit_entry(item, None, action=0, user=user, changes={"quantity": [None, "4"]})

    events = list(_run())

    assert len(events) == 1
    assert events[0].kind == "created"
    assert events[0].quantity == Decimal("4")


@pytest.mark.django_db
def test_backfill_ignores_unrelated_entries(stock_item_factory, audit_entry):
    """Entries without NFC-relevant deltas, or on units unknown to the plugin, are ignored."""
    known = stock_item_factory(metadata={"container_type": "Ampoule"})
    unknown = stock_item_factory()
    _clear_native_audit()

    audit_entry(known, None)
    audit_entry(known, {"location": {"model_type": "stock.stocklocation", "pk": 1}})
    audit_entry(unknown, {"quantity": 2.0, "added": 1.0})

    assert list(_run()) == []


@pytest.mark.django_db
def test_backfill_link_fallback(stock_item_factory, nfc_link_factory, user):
    """A link known only through NFCTagLink yields a link and an unlink event."""
    from django.utils import timezone

    from nfc.models import NFCTagLink

    item = stock_item_factory()
    link = nfc_link_factory(uid="CAFE", stock_item=item, active=True)
    linked_at = timezone.now() - timedelta(days=3)
    unlinked_at = timezone.now() - timedelta(days=1)
    NFCTagLink.objects.filter(pk=link.pk).update(
        linked_at=linked_at,
        linked_by=user,
        active=False,
        unlinked_at=unlinked_at,
        unlinked_by=user,
    )
    _clear_native_audit()

    events = list(_run())

    assert [(e.kind, e.uid, e.date, e.user_id) for e in events] == [
        ("link", "CAFE", linked_at, user.pk),
        ("unlink", "CAFE", unlinked_at, user.pk),
    ]


@pytest.mark.django_db
def test_backfill_no_duplicate_link(stock_item_factory, nfc_link_factory, audit_entry):
    """A link present in both the audit log and NFCTagLink is recorded once."""
    item = stock_item_factory()
    nfc_link_factory(uid="BEEF", stock_item=item, active=True)
    _clear_native_audit()
    audit_entry(item, {"nfc_link": "BEEF"})

    events = list(_run())

    assert [(e.kind, e.uid) for e in events] == [("link", "BEEF")]


@pytest.mark.django_db
def test_backfill_reverse_clears_events(nfc_event_factory):
    """The reverse migration removes every NFC event."""
    from django.apps import apps

    from nfc.models import NFCEvent

    nfc_event_factory()
    backfill.reverse(apps, None)
    assert NFCEvent.objects.count() == 0
