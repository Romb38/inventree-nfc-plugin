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
    Check if an NFC tag UID is linked to a Part.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, uid, *args, **kwargs):
        """
        GET part linked to the NFC tag
        """

        from .models import NFCTagLink

        uid = uid.strip().upper()

        try:
            link = NFCTagLink.objects.get(uid=uid.upper(), active = True)
            part = link.part
            return Response({
                "found": True,
                "uid": uid.upper(),
                "part_id": part.pk,
                "part_name": part.name,
                "part_description": part.description,
                "total_stock": float(part.total_stock),
                "part_url": f"/part/{part.pk}/",
            })
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "uid": uid.upper()})

class NFCLinkView(APIView):
    """
    POST /link/
    Link an NFC tag UID to an InvenTree Part.
    Body: { "uid": "AABBCCDD", "part_id": 42 }
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        from part.models import Part
        from .models import NFCTagLink

        uid = str(request.data.get("uid", "")).strip().upper()
        part_id = request.data.get("part_id")

        if not uid or not part_id:
            return Response(
                {"error": "Both 'uid' and 'part_id' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            part = Part.objects.get(pk=part_id)
        except Part.DoesNotExist:
            return Response(
                {"error": f"Part with id {part_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if NFCTagLink.objects.filter(uid=uid, active=True).exists():
            return Response(
                {"error": f"Tag {uid} is already linked to a part. Unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )

        if NFCTagLink.objects.filter(part=part, active=True).exists():
            return Response(
                {"error": f"Part '{part.name}' already has an active NFC tag linked. Unlink it first."},
                status=status.HTTP_409_CONFLICT,
            )

        link = NFCTagLink.objects.create(
            uid=uid,
            part=part,
            linked_by=request.user,
            active=True,
        )

        return Response({
            "success": True,
            "created": True,
            "uid": link.uid,
            "part_id": part.pk,
            "part_name": part.name,
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
        if not stock_item_id:
            missing.append("stock_item_id")
        if quantity <= 0:
            missing.append("quantity > 0")
        if missing:
            return Response(
                {"error": f"Missing/invalid: {', '.join(missing)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            link = NFCTagLink.objects.select_related("part").get(uid=uid, active=True)
        except NFCTagLink.DoesNotExist:
            return Response(
                {"error": "Tag not linked to any active part."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db import transaction

        with transaction.atomic():
            try:
                stock_item = StockItem.objects.select_for_update().get(
                    pk=stock_item_id, part=link.part
                )
            except StockItem.DoesNotExist:
                return Response(
                    {"error": f"Matching stock item not found for linked part '{link.part.name}'."},
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
            "part_name": link.part.name,
            "action": action,
            "quantity_changed": str(quantity),
            "new_stock": float(stock_item.quantity),
        })

class NFCTagByPartView(APIView):
    """
    GET /tag/by-part/<part_id>/
    Returns the NFC tag linked to a given part, or not_found.
    Used by the Part detail panel to show current tag status.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, part_id, *args, **kwargs):
        from .models import NFCTagLink

        try:
            link = NFCTagLink.objects.select_related("part", "linked_by").get(
                part_id=part_id, active=True
            )
            return Response({
                "found": True,
                "uid": link.uid,
                "part_id": link.part.pk,
                "part_name": link.part.name,
                "linked_at": link.linked_at,
                "linked_by": link.linked_by.username if link.linked_by else None,
            })
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "part_id": part_id})

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
    List the in-stock StockItems for the part linked to an NFC tag.
    Powers the Path A picker: the tag names the Part, the user picks the StockItem.
    """

    permission_classes: ClassVar = [permissions.IsAuthenticated]

    def get(self, request, uid, *args, **kwargs):
        from stock.models import StockItem
        from .models import NFCTagLink

        uid = uid.strip().upper()

        try:
            link = NFCTagLink.objects.select_related("part").get(uid=uid, active=True)
        except NFCTagLink.DoesNotExist:
            return Response({"found": False, "uid": uid})

        items = (
            StockItem.objects.filter(part=link.part, quantity__gt=0)
            .select_related("location")
            .order_by("-quantity")
        )

        return Response({
            "found": True,
            "uid": uid,
            "part_id": link.part.pk,
            "part_name": link.part.name,
            "stock_items": [
                {
                    "id": si.pk,
                    "quantity": float(si.quantity),
                    "location": si.location.name if si.location else None,
                    "batch": si.batch or None,
                }
                for si in items
            ],
        })
