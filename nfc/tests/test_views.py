"""
Tests for NFC plugin API views (stock-item based model).
Uses DRF APIRequestFactory with forced authentication.
"""
import pytest
from nfc.views import (
    NFCTagView,
    NFCLinkView,
    NFCUnlinkView,
    NFCTagByStockItemView,
    NFCCreateProductView,
    NFCCreateItemView,
    NFCPartInfoView,
    NFCStockView,
    NFCHistoryView,
)


@pytest.fixture()
def auth_user(db, django_user_model):
    return django_user_model.objects.create_user(username="tester", password="pass")


@pytest.fixture()
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username="staff", password="pass", is_staff=True
    )


@pytest.fixture()
def rf():
    from rest_framework.test import APIRequestFactory
    return APIRequestFactory()


def _call(view, request, **kwargs):
    res = view(request, **kwargs)
    res.render()
    return res


# --- GET /tag/<uid>/ ---

# Ensure the tag lookup returns the associated stock item when the UID exists.
@pytest.mark.django_db
def test_tag_view_found(rf, auth_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 200
    assert res.data["found"] is True
    assert res.data["uid"] == "AABBCCDD"
    assert "part" in res.data and "scanned_tube" in res.data and "sibling_tubes" in res.data


# Verify the API returns a clear not-found response for an unknown tag UID.
@pytest.mark.django_db
def test_tag_view_not_found(rf, auth_user):
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="UNKNOWN1")
    assert res.status_code == 200
    assert res.data["found"] is False


# Confirm UID lookups are case-insensitive and still match the linked tag.
@pytest.mark.django_db
def test_tag_view_uid_case_insensitive(rf, auth_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="aabbccdd")
    assert res.data["found"] is True


# --- POST /link/ ---

# Check that a valid UID and stock item can be linked successfully.
@pytest.mark.django_db
def test_link_view_success(rf, auth_user, stock_item_factory):
    item = stock_item_factory()
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": item.pk}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.data.get("success") is True
    assert res.data["stock_item_id"] == item.pk


# Ensure the link API rejects incomplete payloads with a bad request response.
@pytest.mark.django_db
def test_link_view_missing_fields(rf, auth_user):
    request = rf.post("/", {"uid": "AABBCCDD"}, format="json"); request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 400


# Confirm duplicate active UIDs are rejected to prevent conflicting tags.
@pytest.mark.django_db
def test_link_view_duplicate_uid(rf, auth_user, nfc_link_factory, stock_item_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    item2 = stock_item_factory()
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": item2.pk}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 409


# Ensure a stock item cannot be linked to a second live tag while already linked.
@pytest.mark.django_db
def test_link_view_stock_item_already_linked(rf, auth_user, nfc_link_factory):
    link = nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.post("/", {"uid": "11223344", "stock_item_id": link.stock_item_id}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 409


# Verify the API reports a missing stock item when a bad item ID is supplied.
@pytest.mark.django_db
def test_link_view_stock_item_not_found(rf, auth_user):
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": 999999}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 404


# --- DELETE /link/<uid>/ ---

# Check that an authorized user can unlink an active tag successfully.
@pytest.mark.django_db
def test_unlink_view_success(rf, staff_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.delete("/"); request.user = staff_user
    res = _call(NFCUnlinkView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 200
    assert res.data["success"] is True


# Confirm the unlink request returns a not-found response for an unknown UID.
@pytest.mark.django_db
def test_unlink_view_not_found(rf, staff_user):
    request = rf.delete("/"); request.user = staff_user
    res = _call(NFCUnlinkView.as_view(), request, uid="NOTEXIST")
    assert res.status_code == 404


# Verify unlinking is allowed for any logged-in user, with auditability handled elsewhere.
@pytest.mark.django_db
def test_unlink_allowed_for_any_user(rf, auth_user, nfc_link_factory):
    """Any logged-in user (not just staff) can unlink — accountability is via history."""
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.delete("/"); request.user = auth_user
    res = _call(NFCUnlinkView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 200
    assert res.data["success"] is True


# --- GET /stock-item-tag/<id>/ ---

# Confirm the reverse lookup by stock item ID returns the linked tag UID.
@pytest.mark.django_db
def test_tag_by_stock_item_found(rf, auth_user, nfc_link_factory):
    link = nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagByStockItemView.as_view(), request, stock_item_id=link.stock_item_id)
    assert res.data["found"] is True
    assert res.data["uid"] == "AABBCCDD"


# Ensure the reverse lookup returns a clean no-result response for an unlinked stock item.
@pytest.mark.django_db
def test_tag_by_stock_item_not_found(rf, auth_user, stock_item_factory):
    item = stock_item_factory()
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagByStockItemView.as_view(), request, stock_item_id=item.pk)
    assert res.data["found"] is False


# --- POST /create-product/ ---

# Ensure a valid product payload creates a product and carries the correct name metadata.
@pytest.mark.django_db
def test_create_product_success(rf, auth_user):
    request = rf.post("/", {
        "molecule": "Paracetamol", "dosage": "10 mg/ml",
        "form": "Solution", "manufacturer": "B. Braun", "add_unit": False,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 200
    assert res.data["success"] is True
    assert res.data["reused_existing_part"] is False
    assert res.data["part_name"] == "Paracetamol B. Braun 10 mg/ml Solution"


# Check that creating the same product twice reuses the existing part instead of duplicating it.
@pytest.mark.django_db
def test_create_product_reuses_existing(rf, auth_user):
    body = {
        "molecule": "Paracetamol", "dosage": "10 mg/ml",
        "form": "Solution", "manufacturer": "B. Braun", "add_unit": False,
    }
    r1 = rf.post("/", body, format="json"); r1.user = auth_user
    _call(NFCCreateProductView.as_view(), r1)
    r2 = rf.post("/", body, format="json"); r2.user = auth_user
    res2 = _call(NFCCreateProductView.as_view(), r2)
    assert res2.data["reused_existing_part"] is True


# Make sure required fields are enforced for product creation requests.
@pytest.mark.django_db
def test_create_product_missing_fields(rf, auth_user):
    request = rf.post("/", {"molecule": "Paracetamol"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 400


# Validate that invalid form data does not create a product.
@pytest.mark.django_db
def test_create_product_bad_form(rf, auth_user):
    request = rf.post("/", {
        "molecule": "X", "dosage": "1 mg", "form": "Sirop", "add_unit": False,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 400


# --- POST /create-item/ (location required, no serial, multi-tag) ---

# Ensure item creation fails when a location is omitted.
@pytest.mark.django_db
def test_create_item_requires_location(rf, auth_user, part_factory):
    part = part_factory(name="Amp Part")
    request = rf.post("/", {"part_id": part.pk, "container_type": "Ampoule"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400  # location is required


# Verify the happy path for creating a single ampoule stock item.
@pytest.mark.django_db
def test_create_item_ampoule_success(rf, auth_user, part_factory, location_factory):
    part = part_factory(name="Amp Part 2")
    loc = location_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "location_id": loc.pk,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 200
    assert res.data["success"] is True
    assert res.data["created_count"] == 1


# Confirm the API rejects item creation when the container type is missing.
@pytest.mark.django_db
def test_create_item_missing_container(rf, auth_user, part_factory, location_factory):
    part = part_factory()
    loc = location_factory()
    request = rf.post("/", {"part_id": part.pk, "location_id": loc.pk}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400  # container required


# Check that a Poche item can be created with a specific starting quantity.
@pytest.mark.django_db
def test_create_item_poche_quantity(rf, auth_user, part_factory, location_factory):
    part = part_factory(name="Poche Part")
    loc = location_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Poche",
        "quantity": 200, "location_id": loc.pk,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 200


# Verify a missing part ID returns a not-found error when creating an item.
@pytest.mark.django_db
def test_create_item_part_not_found(rf, auth_user, location_factory):
    loc = location_factory()
    request = rf.post("/", {
        "part_id": 999999, "container_type": "Ampoule", "location_id": loc.pk,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 404


# Ensure expiry dates earlier than reception are rejected during item creation.
@pytest.mark.django_db
def test_create_item_expiry_before_reception(rf, auth_user, part_factory, location_factory):
    part = part_factory()
    loc = location_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "location_id": loc.pk,
        "expiry_date": "2025-01-01", "received_date": "2026-01-01",
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400


# Check that duplicate UID input is rejected when creating tagged items.
@pytest.mark.django_db
def test_create_item_tag_conflict(rf, auth_user, part_factory, location_factory, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    part = part_factory()
    loc = location_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "location_id": loc.pk,
        "uids": ["AABBCCDD"],
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 409


# Confirm a batch of tag IDs creates one stock item per UID.
@pytest.mark.django_db
def test_create_item_multi_tag_creates_many(rf, auth_user, part_factory, location_factory):
    part = part_factory(name="Multi Part")
    loc = location_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "location_id": loc.pk,
        "uids": ["TAG1", "TAG2", "TAG3"],
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    print(res.data)
    assert res.status_code == 200
    assert res.data["created_count"] == 3

# --- GET /part-info/<id>/ ---

# Verify the part-info endpoint returns the expected part metadata when found.
@pytest.mark.django_db
def test_part_info_found(rf, auth_user, part_factory):
    part = part_factory(name="Info Part")
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCPartInfoView.as_view(), request, part_id=part.pk)
    assert res.data["found"] is True
    assert res.data["part_id"] == part.pk


# Confirm the API reports a not-found response for an unknown part ID.
@pytest.mark.django_db
def test_part_info_not_found(rf, auth_user):
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCPartInfoView.as_view(), request, part_id=999999)
    assert res.data["found"] is False


# --- POST /stock/ (remove, out-of-stock) ---

# Ensure removing part of the stock reduces the quantity without marking it out of stock.
@pytest.mark.django_db
def test_stock_remove_reduces_quantity(rf, auth_user, stock_item_factory, nfc_link_factory):
    item = stock_item_factory(quantity=200)
    nfc_link_factory(uid="AABBCCDD", stock_item=item, active=True)
    request = rf.post("/", {
        "uid": "AABBCCDD", "stock_item_id": item.pk,
        "quantity": 50, "action": "remove",
    }, format="json")
    request.user = auth_user
    res = _call(NFCStockView.as_view(), request)
    assert res.status_code == 200
    assert float(res.data["new_stock"]) == 150.0
    assert res.data["out_of_stock"] is False


# Verify that removing the final quantity marks the stock item as out of stock.
@pytest.mark.django_db
def test_stock_remove_all_marks_out_of_stock(rf, auth_user, stock_item_factory, nfc_link_factory):
    item = stock_item_factory(quantity=200)
    nfc_link_factory(uid="AABBCCDD", stock_item=item, active=True)
    request = rf.post("/", {
        "uid": "AABBCCDD", "stock_item_id": item.pk,
        "quantity": 200, "action": "remove",
    }, format="json")
    request.user = auth_user
    res = _call(NFCStockView.as_view(), request)
    assert res.status_code == 200
    assert float(res.data["new_stock"]) == 0.0
    assert res.data["out_of_stock"] is True


# Check that over-removal is rejected with a validation error instead of modifying stock.
@pytest.mark.django_db
def test_stock_remove_too_much_rejected(rf, auth_user, stock_item_factory, nfc_link_factory):
    item = stock_item_factory(quantity=10)
    nfc_link_factory(uid="AABBCCDD", stock_item=item, active=True)
    request = rf.post("/", {
        "uid": "AABBCCDD", "stock_item_id": item.pk,
        "quantity": 50, "action": "remove",
    }, format="json")
    request.user = auth_user
    res = _call(NFCStockView.as_view(), request)
    assert res.status_code == 400


# --- GET /history/<id>/ ---

# Verify the history endpoint returns the stock event list for a known item.
@pytest.mark.django_db
def test_history_found(rf, auth_user, stock_item_factory):
    item = stock_item_factory()
    request = rf.get("/")
    request.user = auth_user
    res = _call(NFCHistoryView.as_view(), request, stock_item_id=item.pk)
    assert res.data["found"] is True
    assert "events" in res.data


# Confirm the history endpoint reports no data for an unknown stock item.
@pytest.mark.django_db
def test_history_not_found(rf, auth_user):
    request = rf.get("/")
    request.user = auth_user
    res = _call(NFCHistoryView.as_view(), request, stock_item_id=999999)
    assert res.data["found"] is False

# --- NFC history (NFCEvent) written by the views ---


def _stock(rf, user, **body):
    request = rf.post("/", body, format="json")
    request.user = user
    return _call(NFCStockView.as_view(), request)


def _events(item):
    from nfc.models import NFCEvent

    return list(NFCEvent.objects.filter(stock_item=item).order_by("date", "pk"))


@pytest.mark.django_db
def test_stock_add_records_event(rf, auth_user, stock_item_factory, nfc_link_factory):
    """Adding stock updates the quantity and records a 'stock' event."""
    item = stock_item_factory(quantity=10)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=5, action="add")
    assert res.status_code == 200
    assert res.data["new_stock"] == 15.0
    assert res.data["out_of_stock"] is False
    [event] = _events(item)
    assert (event.kind, float(event.delta), float(event.quantity)) == ("stock", 5.0, 15.0)
    assert event.user_id == auth_user.pk


@pytest.mark.django_db
def test_stock_partial_remove_records_native_and_nfc_history(
    rf, auth_user, stock_item_factory, nfc_link_factory
):
    """A partial removal goes through InvenTree's stock API (audit log) and the NFC history."""
    from audit.models import AuditLogEntry

    item = stock_item_factory(quantity=10)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=3, action="remove")
    assert res.status_code == 200
    assert res.data["new_stock"] == 7.0
    [event] = _events(item)
    assert (event.kind, float(event.delta)) == ("stock", -3.0)
    assert any(
        (entry.additional_data or {}).get("deltas", {}).get("removed") == 3.0
        for entry in AuditLogEntry.objects.filter(object_id=item.pk)
    )


@pytest.mark.django_db
def test_stock_invalid_action_rejected(rf, auth_user, nfc_link_factory):
    """An unknown action is rejected instead of being treated as 'add'."""
    link = nfc_link_factory(uid="AABBCCDD")
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=1, action="steal")
    assert res.status_code == 400
    assert _events(link.stock_item) == []


@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [0, -1, "abc", None])
def test_stock_invalid_quantity_rejected(rf, auth_user, nfc_link_factory, quantity):
    """A missing, zero, negative or non-numeric quantity is rejected."""
    link = nfc_link_factory(uid="AABBCCDD")
    body = {"uid": "AABBCCDD", "action": "remove"}
    if quantity is not None:
        body["quantity"] = quantity
    res = _stock(rf, auth_user, **body)
    assert res.status_code == 400
    link.stock_item.refresh_from_db()
    assert float(link.stock_item.quantity) == 1.0


@pytest.mark.django_db
def test_stock_unlinked_tag_rejected(rf, auth_user):
    """A tag with no active link is rejected."""
    res = _stock(rf, auth_user, uid="DEADBEEF", quantity=1, action="add")
    assert res.status_code == 400


@pytest.mark.django_db
def test_stock_sibling_of_other_part_not_found(
    rf, auth_user, stock_item_factory, nfc_link_factory
):
    """A stock_item_id from another product is not adjusted."""
    nfc_link_factory(uid="AABBCCDD")
    other = stock_item_factory(quantity=5)
    res = _stock(
        rf, auth_user, uid="AABBCCDD", stock_item_id=other.pk, quantity=1, action="remove"
    )
    assert res.status_code == 404
    other.refresh_from_db()
    assert float(other.quantity) == 5.0


@pytest.mark.django_db
def test_stock_too_much_message_and_unchanged(
    rf, auth_user, stock_item_factory, nfc_link_factory
):
    """Over-removal reports the available quantity and changes nothing."""
    item = stock_item_factory(quantity=10)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=12, action="remove")
    assert res.status_code == 400
    assert res.data["error"] == "Not enough stock. Available: 10."
    item.refresh_from_db()
    assert float(item.quantity) == 10.0
    assert _events(item) == []


@pytest.mark.django_db
def test_consume_serialized_ampoule(rf, auth_user, stock_item_factory, nfc_link_factory):
    """Consuming a serialized ampoule sets it to 0, keeps its number and records 'consumed'."""
    from datetime import date

    from nfc.views import _serialize_tube

    item = stock_item_factory(quantity=1, serial="7")
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=1, action="remove")
    assert res.status_code == 200
    assert res.data["new_stock"] == 0.0
    assert res.data["out_of_stock"] is True
    assert res.data["used_date"] == date.today().isoformat()
    item.refresh_from_db()
    assert _serialize_tube(item)["serial"] == "7"
    [event] = _events(item)
    assert (event.kind, float(event.delta), float(event.quantity)) == ("consumed", -1.0, 0.0)


@pytest.mark.django_db
def test_consume_bag_keeps_unit(rf, auth_user, stock_item_factory, nfc_link_factory):
    """Consuming a whole bag never deletes it, even with delete_on_deplete set."""
    from stock.models import StockItem

    item = stock_item_factory(quantity=10, metadata={"container_type": "Poche"})
    StockItem.objects.filter(pk=item.pk).update(delete_on_deplete=True)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=10, action="remove")
    assert res.status_code == 200
    assert res.data["out_of_stock"] is True
    assert StockItem.objects.filter(pk=item.pk).exists()
    assert [e.kind for e in _events(item)] == ["consumed"]


@pytest.mark.django_db
def test_restock_clears_used_date(rf, auth_user, stock_item_factory, nfc_link_factory):
    """Adding stock to a depleted unit clears its used date."""
    item = stock_item_factory(quantity=2)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    assert _stock(rf, auth_user, uid="AABBCCDD", quantity=2, action="remove").data[
        "used_date"
    ]
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=5, action="add")
    assert res.status_code == 200
    assert res.data["out_of_stock"] is False
    assert res.data["used_date"] is None


@pytest.mark.django_db
def test_tag_kept_after_depletion(rf, auth_user, stock_item_factory, nfc_link_factory):
    """The tag stays linked to a depleted unit, which is still found by a scan."""
    item = stock_item_factory(quantity=1, serial="3")
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    _stock(rf, auth_user, uid="AABBCCDD", quantity=1, action="remove")
    request = rf.get("/")
    request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="AABBCCDD")
    assert res.data["found"] is True
    assert res.data["scanned_tube"]["id"] == item.pk
    assert res.data["scanned_tube"]["out_of_stock"] is True


@pytest.mark.django_db
def test_history_failure_rolls_back_stock(
    rf, auth_user, stock_item_factory, nfc_link_factory, monkeypatch
):
    """If the history cannot be written, the stock change is cancelled and a 500 is returned."""
    import nfc.models

    def broken(*args, **kwargs):
        raise RuntimeError("history down")

    monkeypatch.setattr(nfc.models, "record_event", broken)
    item = stock_item_factory(quantity=10)
    nfc_link_factory(uid="AABBCCDD", stock_item=item)
    res = _stock(rf, auth_user, uid="AABBCCDD", quantity=3, action="remove")
    assert res.status_code == 500
    assert "error" in res.data
    item.refresh_from_db()
    assert float(item.quantity) == 10.0


@pytest.mark.django_db
def test_stock_does_not_log_request_body(
    rf, auth_user, nfc_link_factory, caplog
):
    """The request body is not written to the logs at warning level."""
    import logging

    nfc_link_factory(uid="AABBCCDD")
    with caplog.at_level(logging.WARNING, logger="inventree"):
        _stock(rf, auth_user, uid="AABBCCDD", quantity=1, action="add", notes="secret")
    assert "secret" not in caplog.text


@pytest.mark.django_db
def test_link_and_unlink_record_events(rf, auth_user, stock_item_factory):
    """Linking then unlinking a tag records 'link' then 'unlink' with the UID."""
    item = stock_item_factory()
    request = rf.post("/", {"uid": "cafe", "stock_item_id": item.pk}, format="json")
    request.user = auth_user
    assert _call(NFCLinkView.as_view(), request).status_code == 200
    request = rf.delete("/")
    request.user = auth_user
    assert _call(NFCUnlinkView.as_view(), request, uid="CAFE").status_code == 200
    assert [(e.kind, e.uid, e.user_id) for e in _events(item)] == [
        ("link", "CAFE", auth_user.pk),
        ("unlink", "CAFE", auth_user.pk),
    ]


@pytest.mark.django_db
def test_create_item_records_created_with_uid(
    rf, auth_user, part_factory, location_factory
):
    """Creating units records one 'created' event per unit, carrying its tag UID."""
    from nfc.models import NFCEvent

    part = part_factory()
    location = location_factory()
    request = rf.post(
        "/",
        {
            "part_id": part.pk,
            "container_type": "Ampoule",
            "location_id": location.pk,
            "uids": ["T1", "T2"],
        },
        format="json",
    )
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 200
    events = NFCEvent.objects.filter(stock_item__part=part)
    assert sorted((e.kind, e.uid) for e in events) == [
        ("created", "T1"),
        ("created", "T2"),
    ]


@pytest.mark.django_db
def test_history_lists_events_most_recent_first(rf, auth_user, stock_item_factory, nfc_event_factory):
    """The history returns every event, most recent first, in the panel format."""
    from datetime import timedelta
    from decimal import Decimal

    from django.utils import timezone

    item = stock_item_factory()
    now = timezone.now()
    nfc_event_factory(stock_item=item, kind="created", quantity=Decimal(1), date=now - timedelta(hours=3))
    nfc_event_factory(stock_item=item, kind="link", uid="AABB", date=now - timedelta(hours=2), user=auth_user)
    nfc_event_factory(
        stock_item=item, kind="consumed", quantity=Decimal(0), delta=Decimal(-1), date=now - timedelta(hours=1)
    )
    request = rf.get("/")
    request.user = auth_user
    res = _call(NFCHistoryView.as_view(), request, stock_item_id=item.pk)
    events = res.data["events"]
    assert [e["type"] for e in events] == ["stock", "link", "created"]
    assert events[0]["added"] == -1.0 and events[0]["quantity"] == 0.0
    assert events[1]["uid"] == "AABB" and events[1]["who"] == auth_user.username
    assert events[2]["quantity"] == 1.0 and events[2]["who"] is None
    assert all(e["when"] for e in events)


@pytest.mark.django_db
def test_history_requires_authentication(rf, stock_item_factory):
    """Anonymous users cannot read the history."""
    item = stock_item_factory()
    res = _call(NFCHistoryView.as_view(), rf.get("/"), stock_item_id=item.pk)
    assert res.status_code in (401, 403)


@pytest.mark.django_db
def test_create_product_with_unit_records_created(rf, auth_user, location_factory):
    """Creating a product with its first unit records a 'created' event for that unit."""
    from nfc.models import NFCEvent

    request = rf.post(
        "/",
        {
            "molecule": "Paracetamol",
            "dosage": "10 mg/ml",
            "form": "Solution",
            "manufacturer": "B. Braun",
            "add_unit": True,
            "container_type": "Poche",
            "quantity": 100,
            "location_id": location_factory().pk,
            "uid": "f00d",
        },
        format="json",
    )
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 200
    [event] = NFCEvent.objects.filter(stock_item_id=res.data["stock_item_id"])
    assert (event.kind, event.uid, event.user_id) == ("created", "F00D", auth_user.pk)


# --- product-form-fields ---


def _create_product(rf, user, **fields):
    body = {
        "molecule": "Paracetamol",
        "dosage": "10 mg/ml",
        "form": "Solution",
        "add_unit": False,
        **fields,
    }
    request = rf.post("/", body, format="json")
    request.user = user
    return _call(NFCCreateProductView.as_view(), request)


def _part_params(part_id):
    from django.contrib.contenttypes.models import ContentType
    from part.models import Part

    from common.models import Parameter

    ct = ContentType.objects.get_for_model(Part)
    return {
        p.template.name: p.data
        for p in Parameter.objects.filter(model_type=ct, model_id=part_id)
    }


@pytest.mark.django_db
def test_product_name_starts_with_drug_name(rf, auth_user):
    """The drug name is the first component of the automatic product name."""
    res = _create_product(rf, auth_user, drug_name="Doliprane", manufacturer="B. Braun")
    assert res.status_code == 200
    assert res.data["part_name"] == "Doliprane Paracetamol B. Braun 10 mg/ml Solution"


@pytest.mark.django_db
def test_product_parameters_and_templates_created(rf, auth_user):
    """Missing parameter templates are created and every value is stored."""
    from common.models import ParameterTemplate

    ParameterTemplate.objects.filter(name__in=["Nature", "Excipients"]).delete()
    res = _create_product(
        rf,
        auth_user,
        drug_name="Doliprane",
        manufacturer="B. Braun",
        nature="Médicament formulé",
        excipients="Mannitol, eau ppi",
    )
    assert res.status_code == 200
    params = _part_params(res.data["part_id"])
    assert params == {
        "Drug name": "Doliprane",
        "Molecule (DCI)": "Paracetamol",
        "Dosage": "10 mg/ml",
        "Form": "Solution",
        "Nature": "Médicament formulé",
        "Excipients": "Mannitol, eau ppi",
    }
    assert ParameterTemplate.objects.get(name="Nature").choices == (
        "Médicament formulé,Principe actif"
    )
    assert not ParameterTemplate.objects.filter(name="Laboratory").exists()


@pytest.mark.django_db
def test_product_name_uses_existing_manufacturer_spelling(rf, auth_user):
    """A known manufacturer keeps its stored spelling in the product name."""
    from company.models import Company

    Company.objects.create(name="B. Braun", is_manufacturer=True)
    res = _create_product(rf, auth_user, manufacturer="b. braun")
    assert res.status_code == 200
    assert res.data["part_name"] == "Paracetamol B. Braun 10 mg/ml Solution"
    assert Company.objects.filter(name__iexact="b. braun").count() == 1


@pytest.mark.django_db
def test_product_laboratory_field_ignored(rf, auth_user):
    """A legacy 'laboratory' value is ignored: not in the name, parameters or manufacturers."""
    from company.models import Company, ManufacturerPart

    res = _create_product(rf, auth_user, laboratory="Sanofi")
    assert res.status_code == 200
    assert res.data["part_name"] == "Paracetamol 10 mg/ml Solution"
    assert "Laboratory" not in _part_params(res.data["part_id"])
    assert not Company.objects.filter(name__iexact="Sanofi").exists()
    assert not ManufacturerPart.objects.filter(part_id=res.data["part_id"]).exists()


@pytest.mark.django_db
def test_product_invalid_nature(rf, auth_user):
    """An unknown nature is rejected and no product is created."""
    from part.models import Part

    res = _create_product(rf, auth_user, nature="Autre")
    assert res.status_code == 400
    assert not Part.objects.filter(name__icontains="Paracetamol").exists()


@pytest.mark.django_db
def test_product_excipients_too_long(rf, auth_user):
    """Excipients longer than 500 characters are rejected."""
    res = _create_product(rf, auth_user, excipients="x" * 501)
    assert res.status_code == 400


@pytest.mark.django_db
def test_product_name_too_long(rf, auth_user):
    """An automatic name over 100 characters is rejected with a clear error."""
    res = _create_product(rf, auth_user, drug_name="D" * 90)
    assert res.status_code == 400
    assert "100" in res.data["error"]


@pytest.mark.django_db
def test_product_manufacturer_created_then_reused(rf, auth_user):
    """A new manufacturer company is created, then found again case-insensitively."""
    from company.models import Company, ManufacturerPart

    first = _create_product(rf, auth_user, manufacturer="Fresenius")
    second = _create_product(
        rf, auth_user, molecule="Ibuprofen", manufacturer="fresenius"
    )
    assert first.status_code == second.status_code == 200
    companies = Company.objects.filter(name__iexact="fresenius")
    assert companies.count() == 1
    assert companies.get().is_manufacturer is True
    linked = ManufacturerPart.objects.filter(manufacturer=companies.get())
    assert sorted(mp.part_id for mp in linked) == sorted([
        first.data["part_id"],
        second.data["part_id"],
    ])


@pytest.mark.django_db
def test_existing_product_not_modified(rf, auth_user):
    """Re-creating an existing product changes neither its parameters nor its manufacturer."""
    from company.models import ManufacturerPart

    first = _create_product(
        rf, auth_user, nature="Principe actif", manufacturer="Fresenius"
    )
    again = _create_product(
        rf, auth_user, nature="Médicament formulé", manufacturer="fresenius"
    )
    assert again.data["reused_existing_part"] is True
    assert again.data["part_id"] == first.data["part_id"]
    assert _part_params(first.data["part_id"])["Nature"] == "Principe actif"
    assert ManufacturerPart.objects.filter(part_id=first.data["part_id"]).count() == 1


@pytest.mark.django_db
def test_manufacturer_suggestions(rf, auth_user):
    """The suggestions endpoint lists manufacturer companies only, sorted by name."""
    from company.models import Company

    from nfc.views import NFCManufacturersView

    Company.objects.create(name="Zeta", is_manufacturer=True)
    Company.objects.create(name="Alpha", is_manufacturer=True)
    Company.objects.create(name="Supplier only", is_manufacturer=False, is_supplier=True)
    request = rf.get("/")
    request.user = auth_user
    res = _call(NFCManufacturersView.as_view(), request)
    assert res.data["results"] == ["Alpha", "Zeta"]


def _create_item(rf, user, **body):
    request = rf.post("/", body, format="json")
    request.user = user
    return _call(NFCCreateItemView.as_view(), request)


def _solution_part(rf, user, form="Solution"):
    from part.models import Part

    res = _create_product(rf, user, form=form)
    return Part.objects.get(pk=res.data["part_id"])


@pytest.mark.django_db
@pytest.mark.parametrize("container", ["Flacon Solution", "Seringue"])
def test_solution_container_unit_in_mg(rf, auth_user, location_factory, container):
    """'Flacon Solution' and 'Seringue' units keep their quantity and are managed in mg."""
    from stock.models import StockItem

    from nfc.views import _serialize_tube

    part = _solution_part(rf, auth_user)
    res = _create_item(
        rf,
        auth_user,
        part_id=part.pk,
        container_type=container,
        location_id=location_factory().pk,
        quantity=500,
    )
    assert res.status_code == 200
    item = StockItem.objects.get(pk=res.data["created"][0]["stock_item_id"])
    tube = _serialize_tube(item)
    assert (tube["quantity"], tube["unit"], tube["behaviour"]) == (500.0, "mg", "quantity")


@pytest.mark.django_db
@pytest.mark.parametrize("container", ["Flacon Solution", "Seringue"])
def test_solution_container_refused_for_powder(rf, auth_user, location_factory, container):
    """'Flacon Solution' and 'Seringue' are refused for a powder product."""
    part = _solution_part(rf, auth_user, form="Poudre")
    res = _create_item(
        rf,
        auth_user,
        part_id=part.pk,
        container_type=container,
        location_id=location_factory().pk,
        quantity=500,
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_several_syringes_with_count(rf, auth_user, location_factory):
    """Three 50 mg syringes are created as three units of quantity 50."""
    from stock.models import StockItem

    part = _solution_part(rf, auth_user)
    res = _create_item(
        rf,
        auth_user,
        part_id=part.pk,
        container_type="Seringue",
        location_id=location_factory().pk,
        quantity=50,
        count=3,
    )
    assert res.status_code == 200
    ids = [c["stock_item_id"] for c in res.data["created"]]
    assert len(ids) == 3
    assert {float(i.quantity) for i in StockItem.objects.filter(pk__in=ids)} == {50.0}
    assert {i.metadata["container_type"] for i in StockItem.objects.filter(pk__in=ids)} == {"Seringue"}


# --- unit-form-rework ---


@pytest.mark.django_db
def test_unit_new_location_created_at_root(rf, auth_user, part_factory):
    """An unknown location name creates a root, non-structural location."""
    from stock.models import StockLocation

    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_name="  Frigo 2 ",
    )
    assert res.status_code == 200
    location = StockLocation.objects.get(pk=res.data["location_id"])
    assert (location.name, location.parent_id, location.structural) == (
        "Frigo 2",
        None,
        False,
    )


@pytest.mark.django_db
def test_unit_existing_location_reused(rf, auth_user, part_factory):
    """An existing root location is reused, whatever the case."""
    from stock.models import StockLocation

    existing = StockLocation.objects.create(name="frigo 2")
    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_name="Frigo 2",
    )
    assert res.data["location_id"] == existing.pk
    assert StockLocation.objects.filter(name__iexact="frigo 2").count() == 1


@pytest.mark.django_db
def test_unit_location_name_with_slash(rf, auth_user, part_factory):
    """A '/' is part of the location name and creates no sub-level."""
    from stock.models import StockLocation

    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_name="Armoire A / Bac 3",
    )
    location = StockLocation.objects.get(pk=res.data["location_id"])
    assert (location.name, location.parent_id) == ("Armoire A / Bac 3", None)
    assert StockLocation.objects.filter(name__in=["Armoire A", "Bac 3"]).count() == 0


@pytest.mark.django_db
def test_unit_structural_location_refused(rf, auth_user, part_factory):
    """A structural root location cannot receive units."""
    from stock.models import StockItem, StockLocation

    StockLocation.objects.create(name="Pharmacie", structural=True)
    part = part_factory()
    res = _create_item(
        rf, auth_user, part_id=part.pk, container_type="Ampoule", location_name="Pharmacie"
    )
    assert res.status_code == 400
    assert not StockItem.objects.filter(part=part).exists()


@pytest.mark.django_db
def test_unit_location_missing(rf, auth_user, part_factory):
    """A storage location is required."""
    res = _create_item(rf, auth_user, part_id=part_factory().pk, container_type="Ampoule")
    assert res.status_code == 400


@pytest.mark.django_db
def test_unit_count_with_partial_tags(rf, auth_user, part_factory, location_factory):
    """count=3 with two tags creates three units, two of them tagged."""
    from nfc.models import NFCTagLink

    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        count=3,
        uids=["t1", "", "T2"],
    )
    assert res.status_code == 200
    assert res.data["created_count"] == 3
    assert [c["uid"] for c in res.data["created"]] == ["T1", "T2", None]
    assert NFCTagLink.objects.filter(active=True).count() == 2


@pytest.mark.django_db
def test_unit_count_defaults_to_tags(rf, auth_user, part_factory, location_factory):
    """Without count, one unit is created per tag."""
    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        uids=["T1", "T2"],
    )
    assert res.data["created_count"] == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra",
    [
        {"count": 1, "uids": ["T1", "T2"]},
        {"count": 2, "uids": ["T1", "t1"]},
        {"count": 0},
        {"count": 101},
        {"count": "deux"},
    ],
)
def test_unit_count_and_tags_rejected(rf, auth_user, part_factory, location_factory, extra):
    """Too many tags, duplicated tags and out-of-range counts are rejected."""
    from stock.models import StockItem

    part = part_factory()
    res = _create_item(
        rf,
        auth_user,
        part_id=part.pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        **extra,
    )
    assert res.status_code == 400
    assert not StockItem.objects.filter(part=part).exists()


@pytest.mark.django_db
def test_unit_bags_contenance(rf, auth_user, location_factory):
    """Two 250 mL bags are created with quantity 250 each."""
    from stock.models import StockItem

    part = _solution_part(rf, auth_user)
    res = _create_item(
        rf,
        auth_user,
        part_id=part.pk,
        container_type="Poche",
        location_id=location_factory().pk,
        count=2,
        quantity=250,
    )
    ids = [c["stock_item_id"] for c in res.data["created"]]
    assert [float(q) for q in StockItem.objects.filter(pk__in=ids).values_list("quantity", flat=True)] == [250.0, 250.0]


@pytest.mark.django_db
def test_unit_ampoule_quantity_forced(rf, auth_user, part_factory, location_factory):
    """An ampoule always has quantity 1."""
    from stock.models import StockItem

    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        quantity=5,
    )
    item = StockItem.objects.get(pk=res.data["created"][0]["stock_item_id"])
    assert float(item.quantity) == 1.0


@pytest.mark.django_db
def test_unit_month_dates(rf, auth_user, part_factory, location_factory):
    """Expiry YYYY-MM is stored at the end of the month, reception at the start."""
    from datetime import date

    from stock.models import StockItem

    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        expiry_date="2028-02",
        received_date="2026-11",
    )
    assert res.status_code == 200
    item = StockItem.objects.get(pk=res.data["created"][0]["stock_item_id"])
    assert item.expiry_date == date(2028, 2, 29)
    assert item.metadata["received_date"] == "2026-11-01"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "dates",
    [
        {"expiry_date": "2026-10", "received_date": "2026-11"},
        {"expiry_date": "13/2027"},
    ],
)
def test_unit_bad_dates(rf, auth_user, part_factory, location_factory, dates):
    """Expiry before reception, or an unreadable date, is rejected."""
    res = _create_item(
        rf,
        auth_user,
        part_id=part_factory().pk,
        container_type="Ampoule",
        location_id=location_factory().pk,
        **dates,
    )
    assert res.status_code == 400
