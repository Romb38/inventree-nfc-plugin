"""
Tests for the NFC plugin entry point (nfc.core).
"""

import pytest

from nfc.core import NFC


@pytest.fixture()
def plugin(db):
    return NFC()


@pytest.mark.parametrize("model", ["part", "stockitem", "partcategory"])
def test_panel_offered(plugin, rf, model):
    """The NFC panel is offered on part, unit and parts index pages."""
    panels = plugin.get_ui_panels(rf.get("/"), {"target_model": model, "target_id": 1})
    assert [p["key"] for p in panels] == ["nfc-panel"]


@pytest.mark.parametrize("model", ["stocklocation", "salesorder", None])
def test_panel_not_offered(plugin, rf, model):
    """The NFC panel is not offered on stock locations nor on other pages."""
    assert plugin.get_ui_panels(rf.get("/"), {"target_model": model}) == []
