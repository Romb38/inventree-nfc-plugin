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
        "form": "Solution", "laboratory": "B. Braun", "add_unit": False,
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
        "form": "Solution", "laboratory": "B. Braun", "add_unit": False,
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