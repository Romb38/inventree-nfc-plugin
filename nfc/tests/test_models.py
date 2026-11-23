"""
Tests for NFCTagLink model logic (stock-item based model).
"""
import pytest


# Verify that UID values are normalized to uppercase when saved.
@pytest.mark.django_db
def test_uid_is_uppercased_on_save(nfc_link_factory):
    """UID must be stored uppercase regardless of input."""
    link = nfc_link_factory(uid="aabbccdd")
    assert link.uid == "AABBCCDD"


# Verify that surrounding whitespace is stripped before the UID is stored.
@pytest.mark.django_db
def test_uid_is_stripped_on_save(nfc_link_factory):
    """Leading/trailing whitespace must be stripped from UID."""
    link = nfc_link_factory(uid="  AABBCCDD  ")
    assert link.uid == "AABBCCDD"


# Ensure the model string representation includes the UID and linked stock item.
@pytest.mark.django_db
def test_str_representation(nfc_link_factory):
    """__str__ should return 'NFC <uid> : stock #<id>'."""
    link = nfc_link_factory(uid="AABBCCDD")
    assert str(link) == f"NFC AABBCCDD : stock #{link.stock_item_id}"


# Ensure a duplicate active UID is rejected to keep one tag bound to one item.
@pytest.mark.django_db
def test_unique_active_uid_constraint(nfc_link_factory, stock_item_factory):
    """Two active links with the same UID must be rejected."""
    from django.db import IntegrityError
    item1 = stock_item_factory()
    item2 = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item1, active=True)
    with pytest.raises(IntegrityError):
        nfc_link_factory(uid="AABBCCDD", stock_item=item2, active=True)


# Confirm that a previously inactive UID can be reused for a new active tag link.
@pytest.mark.django_db
def test_inactive_uid_allows_reuse(nfc_link_factory, stock_item_factory):
    """An inactive link's UID can be reused for a new active link."""
    item1 = stock_item_factory()
    item2 = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item1, active=False)
    link2 = nfc_link_factory(uid="AABBCCDD", stock_item=item2, active=True)
    assert link2.pk is not None


# Ensure one stock item cannot have more than one active NFC link at once.
@pytest.mark.django_db
def test_unique_active_stock_item_constraint(nfc_link_factory, stock_item_factory):
    """A stock item can only have one active NFC tag at a time."""
    from django.db import IntegrityError
    item = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item, active=True)
    with pytest.raises(IntegrityError):
        nfc_link_factory(uid="11223344", stock_item=item, active=True)


@pytest.mark.django_db
def test_record_event_stores_fields(stock_item_factory, django_user_model):
    """record_event must persist every field and normalize the UID."""
    from decimal import Decimal

    from nfc.models import NFCEvent, record_event

    user = django_user_model.objects.create_user(username="ev", password="pass")
    item = stock_item_factory(quantity=10)
    event = record_event(
        item,
        NFCEvent.KIND_STOCK,
        user,
        quantity=Decimal("7"),
        delta=Decimal("-3"),
        uid=" aabb ",
        notes="test",
    )
    event.refresh_from_db()
    assert event.stock_item_id == item.pk
    assert event.kind == "stock"
    assert event.user_id == user.pk
    assert event.quantity == Decimal("7")
    assert event.delta == Decimal("-3")
    assert event.uid == "AABB"
    assert event.notes == "test"
    assert event.date is not None


@pytest.mark.django_db
def test_record_event_rejects_unknown_kind(stock_item_factory):
    """An unknown event kind must raise instead of being silently stored."""
    from nfc.models import NFCEvent, record_event

    with pytest.raises(ValueError):
        record_event(stock_item_factory(), "bogus", None)
    assert NFCEvent.objects.count() == 0


@pytest.mark.django_db
def test_record_event_ignores_anonymous_user(stock_item_factory):
    """An anonymous user is stored as no user."""
    from django.contrib.auth.models import AnonymousUser

    from nfc.models import NFCEvent, record_event

    event = record_event(stock_item_factory(), NFCEvent.KIND_LINK, AnonymousUser())
    assert event.user_id is None


@pytest.mark.django_db
def test_events_ordered_most_recent_first(nfc_event_factory, stock_item_factory):
    """Default ordering is most recent first, then highest pk on equal dates."""
    from datetime import timedelta

    from django.utils import timezone

    from nfc.models import NFCEvent

    item = stock_item_factory()
    now = timezone.now()
    old = nfc_event_factory(stock_item=item, date=now - timedelta(days=1))
    new = nfc_event_factory(stock_item=item, date=now)
    same = nfc_event_factory(stock_item=item, date=now)
    assert list(NFCEvent.objects.filter(stock_item=item)) == [same, new, old]


@pytest.mark.django_db
def test_event_kept_when_user_deleted(nfc_event_factory, django_user_model):
    """Deleting a user keeps their events, with no user attached."""
    user = django_user_model.objects.create_user(username="gone", password="pass")
    event = nfc_event_factory(user=user)
    user.delete()
    event.refresh_from_db()
    assert event.user_id is None
