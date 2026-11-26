"""
API Views for the NFC plugin.
"""

import logging
from decimal import Decimal
from typing import ClassVar

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView, set_rollback

logger = logging.getLogger("inventree")


class NFCActionRefused(Exception):
    """Raised inside an NFC action to abort it (rolling back the transaction) with a 400 error."""


class NFCAPIView(APIView):
    """Base view for NFC endpoints which modify or report the NFC history.

    Errors are never swallowed: an NFCActionRefused becomes a 400 response, and
    any unexpected exception is logged and returned as a JSON 500 response. In
    both cases the exception has already rolled back the enclosing
    transaction, so no partial change is persisted.
    """

    def handle_exception(self, exc):
        """Convert NFC and unexpected errors into JSON error responses."""
        if isinstance(exc, APIException):
            return super().handle_exception(exc)

        set_rollback()

        if isinstance(exc, NFCActionRefused):
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.exception("NFC: %s %s failed", self.request.method, self.request.path)
        return Response(
            {"error": "The NFC action failed and was cancelled. See the server logs."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _change_stock(stock_item, action, quantity, user, notes):
    """Apply a stock change to a locked unit through InvenTree's stock API.

    Partial changes use StockItem.add_stock / take_stock, which record the
    change in InvenTree's own audit log. Consuming the whole remaining
    quantity of a serialized unit (which InvenTree refuses to decrement) keeps
    its serial in metadata["used_serial"] and writes the zero quantity directly.
    Depleted units are never deleted.

    Args:
        stock_item: The StockItem, locked for update.
        action: "add" or "remove".
        quantity: Positive Decimal quantity, not above the available quantity for "remove".
        user: The user performing the action.
        notes: Notes recorded with the change.

    Returns:
        A (kind, delta) tuple: the NFCEvent kind and the signed quantity change.

    Raises:
        NFCActionRefused: If InvenTree refuses the change.
    """
    from .models import NFCEvent

    if action == "add":
        if not stock_item.add_stock(quantity, user, notes=notes):
            raise NFCActionRefused("InvenTree refused to add stock to this unit.")
        stock_item.refresh_from_db()
        return NFCEvent.KIND_STOCK, quantity

    if quantity < stock_item.quantity:
        if not stock_item.take_stock(quantity, user, notes=notes):
            raise NFCActionRefused("InvenTree refused to remove stock from this unit.")
        stock_item.refresh_from_db()
        return NFCEvent.KIND_STOCK, -quantity

    if stock_item.serialized:
        stock_item.metadata = {
            **(stock_item.metadata or {}),
            "used_serial": str(stock_item.serial),
        }
        stock_item.serial = None
        stock_item.quantity = Decimal(0)
        stock_item.delete_on_deplete = False
        stock_item.save()
    else:
        if stock_item.delete_on_deplete:
            stock_item.delete_on_deplete = False
            stock_item.save()
        if not stock_item.take_stock(quantity, user, notes=notes):
            raise NFCActionRefused("InvenTree refused to consume this unit.")
        stock_item.refresh_from_db()

    return NFCEvent.KIND_CONSUMED, -quantity


CONTAINER_TYPES = ("Ampoule", "Poche", "Flacon Solution", "Seringue", "Flacon poudre")

ALLOWED_CONTAINERS_BY_FORM = {
    "Solution": ("Ampoule", "Poche", "Flacon Solution", "Seringue"),
    "Poudre": ("Flacon poudre",),
}

MAX_UNITS_PER_REQUEST = 100


def _container_behaviour(container_type):
    """Map a container type to its stock behaviour and unit of measure.

    Returns:
        A (behaviour, unit) tuple: behaviour is "whole" (consumed at once,
        quantity 1) or "quantity" (consumed by amount), unit is "mL", "mg" or None.
    """
    if container_type == "Poche":
        return "quantity", "mL"
    if container_type in ("Flacon poudre", "Flacon Solution", "Seringue"):
        return "quantity", "mg"
    return "whole", None


def _serialize_tube(stock_item):
    """
    Serialize one Stock Item (physical unit) for display.

    A unit carries: lot (batch), expiry, reception date, unit number (serial),
    location, and its CONTAINER TYPE (stored per-unit in metadata). The
    container type drives how the unit's quantity is managed.
    """
    meta = stock_item.metadata or {}
    container_type = meta.get("container_type") or "Ampoule"
    behaviour, unit = _container_behaviour(container_type)

    return {
        "id": stock_item.pk,
        "serial": stock_item.serial or meta.get("used_serial") or None,
        "batch": stock_item.batch or None,
        "expiry_date": stock_item.expiry_date.isoformat()
        if stock_item.expiry_date
        else None,
        "received_date": meta.get("received_date"),
        "location": stock_item.location.name if stock_item.location else None,
        "quantity": float(stock_item.quantity),
        "out_of_stock": float(stock_item.quantity) <= 0,
        "used_date": meta.get("used_date"),
        "container_type": container_type,
        "behaviour": behaviour,  # "whole" or "quantity"
        "unit": unit,  # "mL", "mg", or None
    }


def _serialize_part(part):
    """Serialize the shared product (Part) info."""
    from common.models import Parameter

    params = {
        p.template.name: p.data
        for p in Parameter.objects.filter(
            model_type=_part_content_type(), model_id=part.pk
        ).select_related("template")
        if p.template
    }
    return {
        "part_id": part.pk,
        "part_name": part.name,
        "part_description": part.description,
        "total_stock": float(part.total_stock),
        "parameters": params,
        # Form (Solution/Poudre) is used by the unit form to offer only the
        # container types valid for this product.
        "form": params.get(PARAM_FORM),
    }


class NFCConfigView(APIView):
    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from plugin.registry import registry

        plugin = registry.get_plugin("nfc")
        return Response({
            # URL + timeout are configured PER WORKSTATION in the browser; these
            # are only defaults/fallbacks used when a workstation hasn't set its
            # own. "localhost" is machine-relative, so it's a safe default.
            "agent_base_url": "http://127.0.0.1:8765",
            "scan_timeout_seconds": 30,
            "sound_enabled": bool(plugin.get_setting("SOUND_ENABLED")),
            "auto_redirect": bool(plugin.get_setting("AUTO_REDIRECT")),
            "allow_link_from_scan": bool(plugin.get_setting("ALLOW_LINK_FROM_SCAN")),
        })


class NFCTagView(APIView):
    """
    GET /tag/<uid>/
    Resolve an NFC tag UID to its tube (StockItem), and return:
      - the shared product (Part) info
      - the scanned tube (highlighted, the default add/remove target)
      - sibling tubes (other StockItems of the same Part)
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, uid, *args, **kwargs):
        from stock.models import StockItem

        from .models import NFCTagLink

        uid = uid.strip().upper()

        try:
            link = NFCTagLink.objects.select_related(
                "stock_item", "stock_item__part", "stock_item__location"
            ).get(uid=uid, active=True)
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "uid": uid})

        tube = link.stock_item
        part = tube.part

        siblings = (
            StockItem.objects.filter(part=part)
            .exclude(pk=tube.pk)
            .select_related("location")
            .order_by("expiry_date", "-quantity")
        )

        return Response({
            "found": True,
            "uid": uid,
            "part": _serialize_part(part),
            "scanned_tube": _serialize_tube(tube),
            "sibling_tubes": [_serialize_tube(si) for si in siblings],
            "part_url": f"/part/{part.pk}/details",
        })


class NFCLinkView(NFCAPIView):
    """
    POST /link/
    Link an NFC tag UID to a specific StockItem (tube).
    Body: { "uid": "AABBCCDD", "stock_item_id": 42 }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from stock.models import StockItem

        from .models import NFCEvent, NFCTagLink, record_event

        uid = str(request.data.get("uid", "")).strip().upper()
        stock_item_id = request.data.get("stock_item_id")

        if not uid or not stock_item_id:
            return Response(
                {"error": "Both 'uid' and 'stock_item_id' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            stock_item = StockItem.objects.select_related("part").get(pk=stock_item_id)
        except StockItem.DoesNotExist:
            return Response(
                {"error": f"Stock item with id {stock_item_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if NFCTagLink.objects.filter(uid=uid, active=True).exists():
            return Response(
                {"error": f"Tag {uid} is already linked. Unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )

        if NFCTagLink.objects.filter(stock_item=stock_item, active=True).exists():
            return Response(
                {"error": "This tube already has an active NFC tag. Unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            link = NFCTagLink.objects.create(
                uid=uid,
                stock_item=stock_item,
                linked_by=request.user,
                active=True,
            )
            record_event(
                stock_item,
                NFCEvent.KIND_LINK,
                request.user,
                uid=uid,
                notes=f"NFC: tag {uid} linked",
            )

        return Response({
            "success": True,
            "created": True,
            "uid": link.uid,
            "stock_item_id": stock_item.pk,
            "part_name": stock_item.part.name,
        })


class NFCStockView(NFCAPIView):
    """
    POST /stock/
    Add or remove stock for a part linked to an NFC tag.
    Body: { "uid": "AABBCCDD", "quantity": 5, "action": "add" | "remove", "notes": "optional" }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from datetime import date
        from decimal import InvalidOperation

        from stock.models import StockItem

        from .models import NFCTagLink, record_event

        uid = str(request.data.get("uid", "")).strip().upper()
        stock_item_id = request.data.get("stock_item_id")
        action = str(request.data.get("action", "add")).strip().lower()
        notes = str(request.data.get("notes", f"NFC {action}")).strip()

        try:
            quantity = Decimal(str(request.data.get("quantity", 0)))
        except (TypeError, ValueError, InvalidOperation):
            return Response(
                {"error": "Quantity must be a number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        missing = []
        if not uid:
            missing.append("uid")
        if action not in ("add", "remove"):
            missing.append("action (add|remove)")
        if not quantity.is_finite() or quantity <= 0:
            missing.append("quantity > 0")
        if missing:
            return Response(
                {"error": f"Missing/invalid: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            link = NFCTagLink.objects.select_related(
                "stock_item", "stock_item__part"
            ).get(uid=uid, active=True)
        except NFCTagLink.DoesNotExist:
            return Response(
                {"error": "Tag not linked to any active tube."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        part = link.stock_item.part

        with transaction.atomic():
            target_id = stock_item_id or link.stock_item_id
            try:
                stock_item = StockItem.objects.select_for_update().get(
                    pk=target_id, part=part
                )
            except (StockItem.DoesNotExist, ValueError, TypeError):
                return Response(
                    {"error": "Target tube not found for this product."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if action == "remove" and stock_item.quantity < quantity:
                available = stock_item.quantity.normalize()
                return Response(
                    {"error": f"Not enough stock. Available: {available:f}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            kind, delta = _change_stock(
                stock_item, action, quantity, request.user, notes
            )

            meta = stock_item.metadata or {}
            if stock_item.quantity <= 0:
                if not meta.get("used_date"):
                    stock_item.metadata = {
                        **meta,
                        "used_date": date.today().isoformat(),
                    }
                    stock_item.save()
            elif meta.get("used_date"):
                meta.pop("used_date", None)
                stock_item.metadata = meta
                stock_item.save()

            record_event(
                stock_item,
                kind,
                request.user,
                quantity=stock_item.quantity,
                delta=delta,
                notes=notes,
            )

        stock_item.refresh_from_db()

        return Response({
            "success": True,
            "part_name": part.name,
            "action": action,
            "quantity_changed": str(quantity),
            "new_stock": float(stock_item.quantity),
            "out_of_stock": float(stock_item.quantity) <= 0,
            "used_date": (stock_item.metadata or {}).get("used_date"),
        })


class NFCTagByStockItemView(APIView):
    """
    GET /stock-item-tag/<stock_item_id>/
    Returns the NFC tag linked to a specific stock item (tube), or not found.
    Used by the panel on a stock item page to show link/unlink state.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, stock_item_id, *args, **kwargs):
        from .models import NFCTagLink

        try:
            link = NFCTagLink.objects.select_related("linked_by").get(
                stock_item_id=stock_item_id, active=True
            )
            return Response({
                "found": True,
                "uid": link.uid,
                "stock_item_id": stock_item_id,
                "linked_at": link.linked_at,
                "linked_by": link.linked_by.username if link.linked_by else None,
            })
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "stock_item_id": stock_item_id})


class NFCTagByPartView(APIView):
    """
    GET /tag/by-part/<part_id>/
    Returns all NFC tags linked to tubes of a given part.
    Used by the Part detail panel to show which tubes are tagged.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, part_id, *args, **kwargs):
        from .models import NFCTagLink

        links = NFCTagLink.objects.select_related("stock_item", "linked_by").filter(
            stock_item__part_id=part_id, active=True
        )

        return Response({
            "found": links.exists(),
            "part_id": part_id,
            "tags": [
                {
                    "uid": link.uid,
                    "stock_item_id": link.stock_item_id,
                    "batch": link.stock_item.batch or None,
                    "linked_at": link.linked_at,
                    "linked_by": link.linked_by.username if link.linked_by else None,
                }
                for link in links
            ],
        })


class NFCUnlinkView(NFCAPIView):
    """
    DELETE /link/<uid>/
    Soft-deletes (deactivates) an NFC tag link.
    Any logged-in user (all actions are recorded with user + timestamp).
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def delete(self, request, uid, *args, **kwargs):
        from django.utils import timezone

        from .models import NFCEvent, NFCTagLink, record_event

        uid = uid.strip().upper()

        with transaction.atomic():
            link = (
                NFCTagLink.objects.select_for_update()
                .filter(uid=uid, active=True)
                .first()
            )
            if link is None:
                return Response(
                    {"error": f"No active link found for UID {uid}."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            link.active = False
            link.unlinked_by = request.user
            link.unlinked_at = timezone.now()
            link.save()

            record_event(
                link.stock_item,
                NFCEvent.KIND_UNLINK,
                request.user,
                uid=uid,
                notes=f"NFC: tag {uid} unlinked",
            )

        return Response({"success": True, "uid": uid})


class NFCStockItemsView(APIView):
    """
    GET /stock-items/<uid>/
    List all tubes (StockItems) of the part linked to a scanned tag.
    Kept for compatibility; the scan endpoint already returns siblings.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, uid, *args, **kwargs):
        from stock.models import StockItem

        from .models import NFCTagLink

        uid = uid.strip().upper()

        try:
            link = NFCTagLink.objects.select_related(
                "stock_item", "stock_item__part"
            ).get(uid=uid, active=True)
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "uid": uid})

        part = link.stock_item.part
        items = (
            StockItem.objects.filter(part=part)
            .select_related("location")
            .order_by("expiry_date", "-quantity")
        )

        return Response({
            "found": True,
            "uid": uid,
            "part": _serialize_part(part),
            "stock_items": [_serialize_tube(si) for si in items],
        })


# ---------------------------------------------------------------------------
# Product (Part) creation — auto-builds the name from lab fields and creates
# the Part + parameters + first stock item (tube) in one call.
# ---------------------------------------------------------------------------

# Parameter template names (must match the templates created in Settings).
PARAM_DRUG_NAME = "Drug name"
PARAM_MOLECULE = "Molecule (DCI)"
PARAM_DOSAGE = "Dosage"
PARAM_FORM = "Form"
PARAM_NATURE = "Nature"
PARAM_EXCIPIENTS = "Excipients"

FORMS = ("Solution", "Poudre")
NATURES = ("Médicament formulé", "Principe actif")
EXCIPIENTS_MAX_LENGTH = 500
PART_NAME_MAX_LENGTH = 100

PARAMETER_TEMPLATES = {
    PARAM_DRUG_NAME: {"description": "Trade name of the medicine (NFC plugin)"},
    PARAM_MOLECULE: {"description": "Active substance, INN (NFC plugin)"},
    PARAM_DOSAGE: {"description": "Mass / concentration (NFC plugin)"},
    PARAM_FORM: {
        "description": "Pharmaceutical form (NFC plugin)",
        "choices": ",".join(FORMS),
    },
    PARAM_NATURE: {
        "description": "Formulated medicine or active substance (NFC plugin)",
        "choices": ",".join(NATURES),
    },
    PARAM_EXCIPIENTS: {"description": "Excipients (NFC plugin)"},
}


def _build_part_name(drug_name, molecule, manufacturer, dosage, form):
    """Build the automatic product name from its non-empty components.

    Example: 'Doliprane Paracétamol B. Braun 10 mg/ml Solution'.
    """
    components = (drug_name, molecule, manufacturer, dosage, form)
    return " ".join(c.strip() for c in components if c and c.strip())


def _get_or_create_category(name):
    """Find the medicines category by name, creating it if missing."""
    from part.models import PartCategory

    cat = PartCategory.objects.filter(name=name).first()
    if cat:
        return cat
    return PartCategory.objects.create(name=name, description="Medicines (NFC plugin)")


def _part_content_type():
    """Return the ContentType of InvenTree's Part model."""
    from django.contrib.contenttypes.models import ContentType
    from part.models import Part

    return ContentType.objects.get_for_model(Part)


def _get_template(name):
    """Return the parameter template `name`, creating it for parts if missing.

    An existing template is returned unchanged, so administrators keep control
    over its settings.
    """
    from common.models import ParameterTemplate

    template = ParameterTemplate.objects.filter(name__iexact=name).first()
    if template:
        return template

    defaults = PARAMETER_TEMPLATES.get(name, {})
    return ParameterTemplate.objects.create(
        name=name,
        model_type=_part_content_type(),
        description=defaults.get("description", ""),
        choices=defaults.get("choices", ""),
    )


def _set_part_parameter(part, template_name, value):
    """Set (create or update) a parameter value on a part.

    Empty values are skipped. The template is created if missing; any other
    failure is raised so the enclosing transaction is rolled back.
    """
    from common.models import Parameter

    if value is None or str(value).strip() == "":
        return

    Parameter.objects.update_or_create(
        model_type=_part_content_type(),
        model_id=part.pk,
        template=_get_template(template_name),
        defaults={"data": str(value).strip()},
    )


def _find_manufacturer(name):
    """Return the manufacturer company named `name` (case-insensitive), or None."""
    from company.models import Company

    if not name:
        return None
    return Company.objects.filter(is_manufacturer=True, name__iexact=name).first()


def _get_or_create_manufacturer(name):
    """Return the manufacturer company named `name` (case-insensitive), creating it if missing."""
    from company.models import Company

    company = _find_manufacturer(name)
    if company:
        return company
    return Company.objects.create(
        name=name,
        description="Manufacturer (NFC plugin)",
        is_manufacturer=True,
        is_supplier=False,
        is_customer=False,
    )


def _attach_manufacturer(part, name):
    """Link `part` to the manufacturer named `name` through a ManufacturerPart."""
    from company.models import ManufacturerPart

    if not name:
        return None
    company = _get_or_create_manufacturer(name)
    ManufacturerPart.objects.get_or_create(part=part, manufacturer=company, MPN=None)
    return company


class NFCManufacturersView(APIView):
    """
    GET /manufacturers/
    Names of the companies flagged as manufacturers, for the product form suggestions.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from company.models import Company

        names = (
            Company.objects.filter(is_manufacturer=True)
            .order_by("name")
            .values_list("name", flat=True)
        )
        return Response({"results": list(names)})


class NFCCreateProductView(NFCAPIView):
    """
    POST /create-product/
    Create a Part (auto-named) + its parameters + first stock item in one call.

    If a Part with the auto-built name already exists, do NOT duplicate it —
    reuse it and just add a new stock item (unit) to it.

    Body:
    {
      "molecule": "Paracétamol", "dosage": "10 mg/ml",
      "form": "Solution", "manufacturer": "B. Braun",
      "batch": "A12345", "expiry_date": "2027-09-30",
      "serial": "1", "location_id": 5, "quantity": 1,
      "uid": "TAG-0001"   # optional, links a tag to the new stock item
    }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from decimal import InvalidOperation

        from part.models import Part
        from stock.models import StockItem, StockLocation

        from .models import NFCEvent, NFCTagLink, record_event

        d = request.data
        drug_name = str(d.get("drug_name", "")).strip()
        molecule = str(d.get("molecule", "")).strip()
        dosage = str(d.get("dosage", "")).strip()
        form = str(d.get("form", "")).strip()
        nature = str(d.get("nature", "") or "").strip()
        manufacturer = str(d.get("manufacturer", "") or "").strip()
        excipients = str(d.get("excipients", "") or "").strip()

        # Product identity requires at least molecule + dosage + form.
        missing = [
            k
            for k, v in {"molecule": molecule, "dosage": dosage, "form": form}.items()
            if not v
        ]
        if missing:
            return Response(
                {"error": f"Missing product fields: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if form not in FORMS:
            return Response(
                {"error": "Form must be 'Solution' or 'Poudre'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if nature and nature not in NATURES:
            return Response(
                {"error": f"Nature must be one of: {', '.join(NATURES)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(excipients) > EXCIPIENTS_MAX_LENGTH:
            return Response(
                {
                    "error": f"Excipients must not exceed {EXCIPIENTS_MAX_LENGTH} characters."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        known_manufacturer = _find_manufacturer(manufacturer)
        if known_manufacturer:
            manufacturer = known_manufacturer.name
        name = _build_part_name(drug_name, molecule, manufacturer, dosage, form)
        if len(name) > PART_NAME_MAX_LENGTH:
            return Response(
                {
                    "error": f"The product name '{name}' exceeds {PART_NAME_MAX_LENGTH} characters. Shorten some fields."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Stock item fields
        batch = str(d.get("batch", "")).strip()
        serial = str(d.get("serial", "")).strip()
        expiry_date = d.get("expiry_date") or None
        received_date = d.get("received_date") or None
        location_id = d.get("location_id")
        uid = str(d.get("uid", "")).strip().upper()

        # If a unit with a tag is requested, reject a tag already in use before
        # creating anything.
        add_unit_early = bool(d.get("add_unit", True))
        if (
            add_unit_early
            and uid
            and NFCTagLink.objects.filter(uid=uid, active=True).exists()
        ):
            return Response(
                {
                    "error": f"Tag {uid} is already linked to another unit. Use a different tag or unlink it first."
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            quantity = Decimal(str(d.get("quantity", 1)))
        except (TypeError, ValueError, InvalidOperation):
            quantity = Decimal(1)

        # A serialized item must have quantity exactly 1 (InvenTree rule).
        if serial:
            quantity = Decimal(1)

        # Category (auto-created if missing) — configurable later via settings.
        category_name = str(d.get("category", "Medicines")).strip() or "Medicines"

        with transaction.atomic():
            existing = Part.objects.filter(name=name).first()
            reused = existing is not None

            if reused:
                part = existing
            else:
                category = _get_or_create_category(category_name)
                part = Part.objects.create(
                    name=name,
                    description=name,
                    category=category,
                    component=False,
                    purchaseable=True,
                    salable=False,
                    active=True,
                )
                for tname, tval in (
                    (PARAM_DRUG_NAME, drug_name),
                    (PARAM_MOLECULE, molecule),
                    (PARAM_DOSAGE, dosage),
                    (PARAM_FORM, form),
                    (PARAM_NATURE, nature),
                    (PARAM_EXCIPIENTS, excipients),
                ):
                    _set_part_parameter(part, tname, tval)
                _attach_manufacturer(part, manufacturer)

            # Stock item is optional: only create a unit if requested.
            add_unit = bool(d.get("add_unit", True))
            stock_item = None
            tag_linked = False

            if add_unit:
                location = None
                if location_id:
                    location = StockLocation.objects.filter(pk=location_id).first()

                stock_item = StockItem.objects.create(
                    part=part,
                    quantity=quantity,
                    batch=batch or "",
                    serial=serial or None,
                    location=location,
                    expiry_date=expiry_date,
                )

                meta_update = {}
                if received_date:
                    meta_update["received_date"] = received_date
                ct = str(d.get("container_type", "")).strip()
                if ct:
                    meta_update["container_type"] = ct
                if meta_update:
                    stock_item.metadata = {**(stock_item.metadata or {}), **meta_update}
                    stock_item.save()

                record_event(
                    stock_item,
                    NFCEvent.KIND_CREATED,
                    request.user,
                    quantity=stock_item.quantity,
                    uid=uid,
                    notes=f"NFC: unit created ({ct or 'unknown container'})",
                )

                if uid:
                    NFCTagLink.objects.create(
                        uid=uid,
                        stock_item=stock_item,
                        linked_by=request.user,
                        active=True,
                    )
                    tag_linked = True

        if add_unit:
            message = (
                "Product already existed — added a new unit to it."
                if reused
                else "Product created with its first unit."
            )
        else:
            message = (
                "Product already existed (no unit added)."
                if reused
                else "Product created (no unit added)."
            )

        return Response({
            "success": True,
            "reused_existing_part": reused,
            "unit_created": add_unit,
            "message": message,
            "part_id": part.pk,
            "part_name": part.name,
            "stock_item_id": stock_item.pk if stock_item else None,
            "tag_linked": tag_linked,
        })


def _parse_month_date(value, end_of_month):
    """Parse 'YYYY-MM' (to the first or last day of the month) or 'YYYY-MM-DD'.

    Args:
        value: The submitted value; empty values give None.
        end_of_month: True to map 'YYYY-MM' to the last day of the month.

    Returns:
        A datetime.date, or None when value is empty.

    Raises:
        ValueError: If value is not a valid month or date.
    """
    import calendar
    import re
    from datetime import date

    text = str(value or "").strip()
    if not text:
        return None
    month = re.fullmatch(r"(\d{4})-(\d{1,2})", text)
    if month:
        year, mon = int(month.group(1)), int(month.group(2))
        day = calendar.monthrange(year, mon)[1] if end_of_month else 1
        return date(year, mon, day)
    return date.fromisoformat(text)


def _resolve_location(location_id, location_name):
    """Return the StockLocation to place new units in.

    A location_id must designate an existing, non-structural location. A
    location_name designates the root location of that name (case-insensitive),
    which is created (non-structural, at the root) when missing.

    Raises:
        NFCActionRefused: If the location is missing, unknown or structural.
    """
    from stock.models import StockLocation

    if location_id not in (None, ""):
        location = StockLocation.objects.filter(pk=location_id).first()
        if location is None:
            raise NFCActionRefused("Location not found.")
    else:
        name = str(location_name or "").strip()
        if not name:
            raise NFCActionRefused("A storage location is required.")
        if len(name) > 100:
            raise NFCActionRefused(
                "The storage location name must not exceed 100 characters."
            )
        location = StockLocation.objects.filter(parent=None, name__iexact=name).first()
        if location is None:
            return StockLocation.objects.create(
                name=name,
                description="Created from the NFC plugin",
                parent=None,
                structural=False,
            )

    if location.structural:
        raise NFCActionRefused(
            "This location is structural (a folder), so stock can't be placed there. Choose another location."
        )
    return location


class NFCCreateItemView(NFCAPIView):
    """
    POST /create-item/
    Create one or more identical stock items (physical units) for an EXISTING part.

    Body:
    {
      "part_id": 924, "container_type": "Poche",
      "location_id": 5,                 # or "location_name": "Frigo 2"
      "count": 3,                       # number of units (default: number of tags, min 1)
      "uids": ["T1", "", "T2"],         # optional tag per unit, empty = no tag
      "quantity": 250,                  # contenance per unit (forced to 1 for ampoules)
      "batch": "A12345",
      "expiry_date": "2027-09",         # last day of the month, or YYYY-MM-DD
      "received_date": "2026-11"        # first day of the month, or YYYY-MM-DD
    }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from decimal import InvalidOperation

        from part.models import Part
        from stock.models import StockItem

        from .models import NFCEvent, NFCTagLink, record_event

        d = request.data
        part_id = d.get("part_id")
        if not part_id:
            return Response(
                {"error": "part_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        part = Part.objects.filter(pk=part_id).first()
        if not part:
            return Response(
                {"error": f"Part {part_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        batch = str(d.get("batch", "")).strip()
        container_type = str(d.get("container_type", "")).strip()

        raw_uids = d.get("uids")
        if raw_uids is None:
            single = str(d.get("uid", "")).strip()
            raw_uids = [single] if single else []
        if not isinstance(raw_uids, (list, tuple)):
            raise NFCActionRefused("'uids' must be a list.")
        uids = [str(u or "").strip().upper() for u in raw_uids]
        tagged = [u for u in uids if u]

        raw_count = d.get("count")
        if raw_count in (None, ""):
            raw_count = max(1, len(tagged))
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            raise NFCActionRefused("The number of units must be a whole number.")
        if not 1 <= count <= MAX_UNITS_PER_REQUEST:
            raise NFCActionRefused(
                f"The number of units must be between 1 and {MAX_UNITS_PER_REQUEST}."
            )
        if len(tagged) > count:
            raise NFCActionRefused("There are more tags than units to create.")
        duplicates = sorted({u for u in tagged if tagged.count(u) > 1})
        if duplicates:
            raise NFCActionRefused(
                f"The same tag is used twice: {', '.join(duplicates)}."
            )

        if not container_type:
            raise NFCActionRefused(
                f"Container type is required ({', '.join(CONTAINER_TYPES)})."
            )
        if container_type not in CONTAINER_TYPES:
            raise NFCActionRefused("Invalid container type.")
        part_form = _serialize_part(part).get("form")
        allowed = ALLOWED_CONTAINERS_BY_FORM.get(part_form)
        if allowed and container_type not in allowed:
            raise NFCActionRefused(
                f"This product is '{part_form}'. Container must be one of: {', '.join(allowed)}."
            )

        behaviour, _unit = _container_behaviour(container_type)
        if behaviour == "whole":
            quantity = Decimal(1)
        else:
            try:
                quantity = Decimal(str(d.get("quantity", 1)))
            except (TypeError, ValueError, InvalidOperation):
                raise NFCActionRefused("Quantity must be a number.")
            if not quantity.is_finite() or quantity <= 0:
                raise NFCActionRefused("Quantity must be greater than 0.")

        try:
            expiry_date = _parse_month_date(d.get("expiry_date"), end_of_month=True)
            received_date = _parse_month_date(
                d.get("received_date"), end_of_month=False
            )
        except ValueError:
            raise NFCActionRefused("Dates must be given as YYYY-MM or YYYY-MM-DD.")
        if expiry_date and received_date and expiry_date < received_date:
            raise NFCActionRefused(
                "Expiry date is before the reception date. Please check the dates."
            )

        conflict = [
            u for u in tagged if NFCTagLink.objects.filter(uid=u, active=True).exists()
        ]
        if conflict:
            return Response(
                {"error": f"These tags are already linked: {', '.join(conflict)}."},
                status=status.HTTP_409_CONFLICT,
            )

        unit_uids = tagged + [None] * (count - len(tagged))

        created = []
        with transaction.atomic():
            location = _resolve_location(d.get("location_id"), d.get("location_name"))

            for one_uid in unit_uids:
                stock_item = StockItem.objects.create(
                    part=part,
                    quantity=quantity,
                    batch=batch or "",
                    location=location,
                    expiry_date=expiry_date,
                )
                stock_item.delete_on_deplete = False

                meta_update = {"container_type": container_type}
                if received_date:
                    meta_update["received_date"] = received_date.isoformat()
                stock_item.metadata = {**(stock_item.metadata or {}), **meta_update}
                stock_item.save()

                record_event(
                    stock_item,
                    NFCEvent.KIND_CREATED,
                    request.user,
                    quantity=stock_item.quantity,
                    uid=one_uid or "",
                    notes=f"NFC: unit created ({container_type})",
                )

                if one_uid:
                    NFCTagLink.objects.create(
                        uid=one_uid,
                        stock_item=stock_item,
                        linked_by=request.user,
                        active=True,
                    )

                created.append({"stock_item_id": stock_item.pk, "uid": one_uid})

        return Response({
            "success": True,
            "part_id": part.pk,
            "part_name": part.name,
            "location_id": location.pk,
            "location_name": location.name,
            "created_count": len(created),
            "created": created,
        })


class NFCPartInfoView(APIView):
    """
    GET /part-info/<part_id>/
    Return a part's display info including container_type/behaviour/unit,
    so the Create Unit form can adapt its fields to the container type.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, part_id, *args, **kwargs):
        from part.models import Part

        part = Part.objects.filter(pk=part_id).first()
        if not part:
            return Response({"found": False})
        data = _serialize_part(part)
        data["found"] = True
        return Response(data)


class NFCHistoryView(NFCAPIView):
    """
    GET /history/<stock_item_id>/
    Return the NFC history of a unit, most recent first, read from NFCEvent:
      - created: unit creation (initial quantity, tag UID if linked at creation)
      - stock: quantity change (a consumption is reported as a stock change to 0)
      - link / unlink: tag link and unlink events
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, stock_item_id, *args, **kwargs):
        from stock.models import StockItem

        item = StockItem.objects.filter(pk=stock_item_id).first()
        if not item:
            return Response({"found": False, "events": []})

        events = [
            _serialize_event(ev)
            for ev in item.nfc_events.select_related("user").order_by("-date", "-pk")
        ]

        return Response({"found": True, "events": events})


def _serialize_event(event):
    """Serialize an NFCEvent in the history format consumed by the panel.

    A "consumed" event is exposed as a "stock" event (negative change, quantity 0)
    so that the panel renders it without knowing the extra kind.
    """
    from .models import NFCEvent

    data = {
        "type": event.kind,
        "when": event.date.isoformat() if event.date else None,
        "who": event.user.username if event.user else None,
    }

    if event.kind in (NFCEvent.KIND_LINK, NFCEvent.KIND_UNLINK):
        data["uid"] = event.uid
    elif event.kind == NFCEvent.KIND_CREATED:
        data["quantity"] = _as_number(event.quantity)
        data["notes"] = event.notes
        if event.uid:
            data["uid"] = event.uid
    else:
        data["type"] = "stock"
        data["quantity"] = _as_number(event.quantity)
        data["added"] = _as_number(event.delta)
        data["notes"] = event.notes

    return data


def _as_number(value):
    """Convert a Decimal to a float for JSON output, keeping None."""
    return None if value is None else float(value)
