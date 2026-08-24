"""
Tests for NFCTagLink model logic (stock-item based model).
"""
import pytest


@pytest.mark.django_db
def test_uid_is_uppercased_on_save(nfc_link_factory):
    """UID must be stored uppercase regardless of input."""
    link = nfc_link_factory(uid="aabbccdd")
    assert link.uid == "AABBCCDD"


@pytest.mark.django_db
def test_uid_is_stripped_on_save(nfc_link_factory):
    """Leading/trailing whitespace must be stripped from UID."""
    link = nfc_link_factory(uid="  AABBCCDD  ")
    assert link.uid == "AABBCCDD"


@pytest.mark.django_db
def test_str_representation(nfc_link_factory):
    """__str__ should return 'NFC <uid> : stock #<id>'."""
    link = nfc_link_factory(uid="AABBCCDD")
    assert str(link) == f"NFC AABBCCDD : stock #{link.stock_item_id}"


@pytest.mark.django_db
def test_unique_active_uid_constraint(nfc_link_factory, stock_item_factory):
    """Two active links with the same UID must be rejected."""
    from django.db import IntegrityError
    item1 = stock_item_factory()
    item2 = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item1, active=True)
    with pytest.raises(IntegrityError):
        nfc_link_factory(uid="AABBCCDD", stock_item=item2, active=True)


@pytest.mark.django_db
def test_inactive_uid_allows_reuse(nfc_link_factory, stock_item_factory):
    """An inactive link's UID can be reused for a new active link."""
    item1 = stock_item_factory()
    item2 = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item1, active=False)
    link2 = nfc_link_factory(uid="AABBCCDD", stock_item=item2, active=True)
    assert link2.pk is not None


@pytest.mark.django_db
def test_unique_active_stock_item_constraint(nfc_link_factory, stock_item_factory):
    """A stock item can only have one active NFC tag at a time."""
    from django.db import IntegrityError
    item = stock_item_factory()
    nfc_link_factory(uid="AABBCCDD", stock_item=item, active=True)
    with pytest.raises(IntegrityError):
        nfc_link_factory(uid="11223344", stock_item=item, active=True)
