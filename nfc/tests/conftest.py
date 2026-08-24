"""
Shared pytest fixtures for the NFC plugin.

The model links an NFC tag to a StockItem (a physical unit), not to a Part.
A Part has many StockItems; each StockItem may carry one active tag.
"""
import pytest


@pytest.fixture
def part_factory(db):
    """Create a minimal InvenTree Part."""
    from part.models import Part, PartCategory

    def make_part(name="Test Part", description="A test part"):
        category, _ = PartCategory.objects.get_or_create(name="Test Category")
        return Part.objects.create(
            name=name,
            description=description,
            category=category,
            is_template=False,
        )

    return make_part


@pytest.fixture
def stock_item_factory(db, part_factory):
    """Create a StockItem (a physical unit) under a Part."""
    from stock.models import StockItem

    def make_item(part=None, quantity=1, batch="", serial=None, metadata=None):
        if part is None:
            part = part_factory()
        item = StockItem.objects.create(
            part=part,
            quantity=quantity,
            batch=batch,
            serial=serial,
        )
        if metadata:
            item.metadata = metadata
            item.save()
        return item

    return make_item


@pytest.fixture
def nfc_link_factory(db, stock_item_factory):
    """Create an NFCTagLink pointing at a StockItem."""
    from nfc.models import NFCTagLink

    def make_link(uid="AABBCCDD", stock_item=None, active=True):
        if stock_item is None:
            stock_item = stock_item_factory()
        return NFCTagLink.objects.create(uid=uid, stock_item=stock_item, active=active)

    return make_link
