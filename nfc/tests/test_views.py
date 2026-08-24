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

@pytest.mark.django_db
def test_tag_view_found(rf, auth_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 200
    assert res.data["found"] is True
    assert res.data["uid"] == "AABBCCDD"
    assert "part" in res.data and "scanned_tube" in res.data and "sibling_tubes" in res.data


@pytest.mark.django_db
def test_tag_view_not_found(rf, auth_user):
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="UNKNOWN1")
    assert res.status_code == 200
    assert res.data["found"] is False


@pytest.mark.django_db
def test_tag_view_uid_case_insensitive(rf, auth_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagView.as_view(), request, uid="aabbccdd")
    assert res.data["found"] is True


# --- POST /link/ ---

@pytest.mark.django_db
def test_link_view_success(rf, auth_user, stock_item_factory):
    item = stock_item_factory()
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": item.pk}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.data.get("success") is True
    assert res.data["stock_item_id"] == item.pk


@pytest.mark.django_db
def test_link_view_missing_fields(rf, auth_user):
    request = rf.post("/", {"uid": "AABBCCDD"}, format="json"); request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 400


@pytest.mark.django_db
def test_link_view_duplicate_uid(rf, auth_user, nfc_link_factory, stock_item_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    item2 = stock_item_factory()
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": item2.pk}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 409


@pytest.mark.django_db
def test_link_view_stock_item_already_linked(rf, auth_user, nfc_link_factory):
    link = nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.post("/", {"uid": "11223344", "stock_item_id": link.stock_item_id}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 409


@pytest.mark.django_db
def test_link_view_stock_item_not_found(rf, auth_user):
    request = rf.post("/", {"uid": "AABBCCDD", "stock_item_id": 999999}, format="json")
    request.user = auth_user
    res = _call(NFCLinkView.as_view(), request)
    assert res.status_code == 404


# --- DELETE /link/<uid>/ ---

@pytest.mark.django_db
def test_unlink_view_success(rf, staff_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.delete("/"); request.user = staff_user
    res = _call(NFCUnlinkView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 200
    assert res.data["success"] is True


@pytest.mark.django_db
def test_unlink_view_not_found(rf, staff_user):
    request = rf.delete("/"); request.user = staff_user
    res = _call(NFCUnlinkView.as_view(), request, uid="NOTEXIST")
    assert res.status_code == 404


@pytest.mark.django_db
def test_unlink_requires_staff(rf, auth_user, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.delete("/"); request.user = auth_user
    res = _call(NFCUnlinkView.as_view(), request, uid="AABBCCDD")
    assert res.status_code == 403


# --- GET /stock-item-tag/<id>/ ---

@pytest.mark.django_db
def test_tag_by_stock_item_found(rf, auth_user, nfc_link_factory):
    link = nfc_link_factory(uid="AABBCCDD", active=True)
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagByStockItemView.as_view(), request, stock_item_id=link.stock_item_id)
    assert res.data["found"] is True
    assert res.data["uid"] == "AABBCCDD"


@pytest.mark.django_db
def test_tag_by_stock_item_not_found(rf, auth_user, stock_item_factory):
    item = stock_item_factory()
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCTagByStockItemView.as_view(), request, stock_item_id=item.pk)
    assert res.data["found"] is False


# --- POST /create-product/ ---

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


@pytest.mark.django_db
def test_create_product_missing_fields(rf, auth_user):
    request = rf.post("/", {"molecule": "Paracetamol"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 400


@pytest.mark.django_db
def test_create_product_bad_form(rf, auth_user):
    request = rf.post("/", {
        "molecule": "X", "dosage": "1 mg", "form": "Sirop", "add_unit": False,
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateProductView.as_view(), request)
    assert res.status_code == 400


# --- POST /create-item/ ---

@pytest.mark.django_db
def test_create_item_ampoule_requires_serial(rf, auth_user, part_factory):
    part = part_factory(name="Amp Part")
    request = rf.post("/", {"part_id": part.pk, "container_type": "Ampoule"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400


@pytest.mark.django_db
def test_create_item_ampoule_success(rf, auth_user, part_factory):
    part = part_factory(name="Amp Part 2")
    request = rf.post("/", {"part_id": part.pk, "container_type": "Ampoule", "serial": "1"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 200
    assert res.data["success"] is True


@pytest.mark.django_db
def test_create_item_missing_container(rf, auth_user, part_factory):
    part = part_factory()
    request = rf.post("/", {"part_id": part.pk, "serial": "1"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400


@pytest.mark.django_db
def test_create_item_poche_quantity(rf, auth_user, part_factory):
    part = part_factory(name="Poche Part")
    request = rf.post("/", {"part_id": part.pk, "container_type": "Poche", "quantity": 200}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 200


@pytest.mark.django_db
def test_create_item_part_not_found(rf, auth_user):
    request = rf.post("/", {"part_id": 999999, "container_type": "Ampoule", "serial": "1"}, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 404


@pytest.mark.django_db
def test_create_item_expiry_before_reception(rf, auth_user, part_factory):
    part = part_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "serial": "1",
        "expiry_date": "2025-01-01", "received_date": "2026-01-01",
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 400


@pytest.mark.django_db
def test_create_item_tag_conflict(rf, auth_user, part_factory, nfc_link_factory):
    nfc_link_factory(uid="AABBCCDD", active=True)
    part = part_factory()
    request = rf.post("/", {
        "part_id": part.pk, "container_type": "Ampoule", "serial": "1", "uid": "AABBCCDD",
    }, format="json")
    request.user = auth_user
    res = _call(NFCCreateItemView.as_view(), request)
    assert res.status_code == 409


# --- GET /part-info/<id>/ ---

@pytest.mark.django_db
def test_part_info_found(rf, auth_user, part_factory):
    part = part_factory(name="Info Part")
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCPartInfoView.as_view(), request, part_id=part.pk)
    assert res.data["found"] is True
    assert res.data["part_id"] == part.pk


@pytest.mark.django_db
def test_part_info_not_found(rf, auth_user):
    request = rf.get("/"); request.user = auth_user
    res = _call(NFCPartInfoView.as_view(), request, part_id=999999)
    assert res.data["found"] is False
