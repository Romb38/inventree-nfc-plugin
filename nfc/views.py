"""
API Views for the NFC plugin.
"""

from typing import ClassVar
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView


def _adjust_stock(stock_item, action, quantity, user, notes):
    """
    Adjust stock in a way that survives InvenTree version differences.

    Different versions expose different method names on StockItem
    (add_stock/remove_stock, addStock/removeStock) or none at all.
    We try the model methods first, then fall back to a direct
    quantity write + tracking entry.
    """
    candidates = {
        "add": ["add_stock", "addStock"],
        "remove": ["take_stock", "removeStock", "remove_stock"],
    }[action]

    for name in candidates:
        method = getattr(stock_item, name, None)
        if callable(method):
            import logging
            logging.getLogger("inventree").info("NFC: stock %s via StockItem.%s()", action, name)
            try:
                return method(quantity, user, notes=notes)
            except TypeError:
                # Some signatures don't accept notes as kwarg
                return method(quantity, user)

    # Fallback: write the quantity directly and log a tracking entry.
    from decimal import Decimal
    delta = quantity if action == "add" else -quantity
    stock_item.quantity = Decimal(str(stock_item.quantity)) + Decimal(str(delta))
    stock_item.save()
    try:
        from stock.models import StockItemTracking
        StockItemTracking.objects.create(
            item=stock_item,
            user=user,
            notes=notes or f"NFC {action} {quantity}",
            deltas={"quantity": float(stock_item.quantity), "added": float(delta)},
        )
    except Exception:
        pass  # tracking is best-effort; quantity change already saved
    return stock_item


def _serialize_tube(stock_item):
    """
    Serialize one StockItem (tube) for display.

    Native InvenTree fields: quantity, batch, expiry_date, location, status.
    Non-native lab fields live in stock_item.metadata (a JSON dict) so display
    stays consistent: every field is always present, None when unset.
    """
    meta = stock_item.metadata or {}

    def m(key):
        return meta.get(key)

    return {
        "id": stock_item.pk,
        "quantity": float(stock_item.quantity),
        "batch": stock_item.batch or None,
        "expiry_date": stock_item.expiry_date.isoformat() if stock_item.expiry_date else None,
        "location": stock_item.location.name if stock_item.location else None,
        "status_label": stock_item.get_status_display() if hasattr(stock_item, "get_status_display") else None,
        # Non-native lab fields (from metadata)
        "concentration": m("concentration"),
        "measured_ph": m("measured_ph"),
        "received_date": m("received_date"),
        "opened_date": m("opened_date"),
        "purity": m("purity"),
        "manufacturer": m("manufacturer"),
    }


def _serialize_part(part):
    """Serialize the shared product (Part) info."""
    params = {}
    try:
        for p in part.get_parameters():
            params[p.template.name] = p.data
    except Exception:
        pass
    return {
        "part_id": part.pk,
        "part_name": part.name,
        "part_description": part.description,
        "total_stock": float(part.total_stock),
        "parameters": params,  # CAS, form, spec_ph, etc. if configured as Part parameters
    }


class NFCConfigView(APIView):
    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from plugin.registry import registry

        plugin = registry.get_plugin('nfc')
        return Response({
            "agent_base_url": plugin.get_setting("AGENT_BASE_URL"),
            "scan_timeout_seconds": int(plugin.get_setting("SCAN_TIMEOUT_SECONDS")),
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

class NFCLinkView(APIView):
    """
    POST /link/
    Link an NFC tag UID to a specific StockItem (tube).
    Body: { "uid": "AABBCCDD", "stock_item_id": 42 }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from stock.models import StockItem
        from .models import NFCTagLink

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

        link = NFCTagLink.objects.create(
            uid=uid,
            stock_item=stock_item,
            linked_by=request.user,
            active=True,
        )

        return Response({
            "success": True,
            "created": True,
            "uid": link.uid,
            "stock_item_id": stock_item.pk,
            "part_name": stock_item.part.name,
        })

class NFCStockView(APIView):
    """
    POST /stock/
    Add or remove stock for a part linked to an NFC tag.
    Body: { "uid": "AABBCCDD", "quantity": 5, "action": "add" | "remove", "notes": "optional" }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from stock.models import StockItem
        from .models import NFCTagLink

        import logging
        logging.getLogger("inventree").warning("NFC stock POST body: %r", dict(request.data))

        uid = str(request.data.get("uid", "")).strip().upper()
        # Optional: adjust a specific tube (e.g. a sibling the user tapped).
        # If omitted, we adjust the tube the tag is linked to.
        stock_item_id = request.data.get("stock_item_id")
        action = str(request.data.get("action", "add")).strip().lower()
        notes = str(request.data.get("notes", f"NFC {action}")).strip()

        from decimal import Decimal, InvalidOperation

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
        if quantity <= 0:
            missing.append("quantity > 0")
        if missing:
            return Response(
                {"error": f"Missing/invalid: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            link = NFCTagLink.objects.select_related("stock_item", "stock_item__part").get(
                uid=uid, active=True
            )
        except NFCTagLink.DoesNotExist:
            return Response(
                {"error": "Tag not linked to any active tube."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        part = link.stock_item.part

        from django.db import transaction

        with transaction.atomic():
            # Default target = the linked tube. Optionally a sibling of same part.
            target_id = stock_item_id or link.stock_item_id
            try:
                stock_item = StockItem.objects.select_for_update().get(
                    pk=target_id, part=part
                )
            except StockItem.DoesNotExist:
                return Response(
                    {"error": "Target tube not found for this product."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if action == "remove":
                if stock_item.quantity < quantity:
                    available = stock_item.quantity.normalize()
                    return Response(
                        {"error": f"Not enough stock. Available: {available:f}."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                _adjust_stock(stock_item, "remove", quantity, request.user, notes)
            else:
                _adjust_stock(stock_item, "add", quantity, request.user, notes)

        stock_item.refresh_from_db()

        return Response({
            "success": True,
            "part_name": part.name,
            "action": action,
            "quantity_changed": str(quantity),
            "new_stock": float(stock_item.quantity),
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

        links = NFCTagLink.objects.select_related(
            "stock_item", "linked_by"
        ).filter(stock_item__part_id=part_id, active=True)

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

class NFCUnlinkView(APIView):
    """
    DELETE /link/<uid>/
    Soft-deletes (deactivates) an NFC tag link.
    Staff only.
    """

    permission_classes: ClassVar = [permissions.IsAdminUser]

    def delete(self, request, uid, *args, **kwargs):
        from .models import NFCTagLink

        uid = uid.strip().upper()

        try:
            link = NFCTagLink.objects.get(uid=uid, active=True)
            link.active = False
            link.save()
            return Response({"success": True, "uid": uid})
        except NFCTagLink.DoesNotExist:
            return Response(
                {"error": f"No active link found for UID {uid}."},
                status=status.HTTP_404_NOT_FOUND,
            )
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
            link = NFCTagLink.objects.select_related("stock_item", "stock_item__part").get(
                uid=uid, active=True
            )
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
