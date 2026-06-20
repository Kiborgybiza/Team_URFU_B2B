import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.models import ProductStatus, ReserveOperation, SKU, UnreserveOperation
from src.services.b2c_service import send_sku_out_of_stock_event

logger = logging.getLogger(__name__)


class ReservationConflictError(Exception):
    def __init__(self, response: dict) -> None:
        self.response = response
        super().__init__("Reservation conflict")


class IdempotencyConflictError(Exception):
    pass


class UnreserveConflictError(Exception):
    pass


def _normalize_items(items: list[dict]) -> list[dict]:
    totals: dict[uuid.UUID, int] = {}
    for item in items:
        sku_id = item["sku_id"]
        totals[sku_id] = totals.get(sku_id, 0) + int(item["quantity"])
    return [
        {"sku_id": k, "quantity": v}
        for k, v in sorted(totals.items(), key=lambda x: str(x[0]))
    ]


def _request_hash(payload: dict) -> str:
    def _safe(v):
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, dict):
            return {k: _safe(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_safe(i) for i in v]
        return v

    raw = json.dumps(_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _lock_skus(db: Session, sku_ids: list[uuid.UUID]) -> dict[uuid.UUID, SKU]:
    skus = db.scalars(
        select(SKU).options(selectinload(SKU.product)).where(SKU.id.in_(sku_ids)).with_for_update()
    ).all()
    return {sku.id: sku for sku in skus}


def _sku_visible(sku: SKU | None) -> bool:
    if sku is None or sku.product is None:
        return False
    return sku.product.status == ProductStatus.MODERATED and not sku.product.deleted and not sku.deleted


def reserve_skus(db: Session, idempotency_key: str, items: list[dict]) -> dict:
    normalized = _normalize_items(items)
    payload_for_hash = {
        "idempotency_key": idempotency_key,
        "items": [{"sku_id": str(i["sku_id"]), "quantity": i["quantity"]} for i in normalized],
    }
    req_hash = _request_hash(payload_for_hash)

    existing = db.get(ReserveOperation, idempotency_key)
    if existing is not None:
        if existing.request_hash != req_hash:
            raise IdempotencyConflictError("idempotency_key used with different payload")
        return existing.response

    operation = ReserveOperation(
        idempotency_key=idempotency_key,
        request_hash=req_hash,
        request_payload=payload_for_hash,
        response={},
    )
    db.add(operation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.get(ReserveOperation, idempotency_key)
        if existing is None:
            raise IdempotencyConflictError("concurrent request with same key")
        if existing.request_hash != req_hash:
            raise IdempotencyConflictError("idempotency_key used with different payload")
        return existing.response

    sku_ids = [i["sku_id"] for i in normalized]
    sku_map = _lock_skus(db, sku_ids)

    failed: list[dict] = []
    for item in normalized:
        sku = sku_map.get(item["sku_id"])
        if not _sku_visible(sku):
            failed.append({"sku_id": str(item["sku_id"]), "requested": item["quantity"], "available": 0, "reason": "OUT_OF_STOCK"})
            continue
        avail = sku.active_quantity
        if avail < item["quantity"]:
            failed.append({
                "sku_id": str(item["sku_id"]),
                "requested": item["quantity"],
                "available": avail,
                "reason": "OUT_OF_STOCK" if avail == 0 else "INSUFFICIENT_STOCK",
            })

    if failed:
        db.rollback()
        raise ReservationConflictError({"reserved": False, "failed_items": failed})

    out_of_stock: list[tuple[uuid.UUID, uuid.UUID]] = []
    response_items = []
    for item in normalized:
        sku = sku_map[item["sku_id"]]
        qty = item["quantity"]
        sku.active_quantity -= qty
        sku.reserved_quantity += qty
        if sku.active_quantity == 0:
            out_of_stock.append((sku.product_id, sku.id))
        response_items.append({
            "sku_id": str(sku.id),
            "reserved_quantity": qty,
            "remaining_stock": sku.active_quantity,
        })

    response: dict = {"reserved": True, "items": response_items}
    operation.response = response
    db.commit()

    for product_id, sku_id in out_of_stock:
        try:
            send_sku_out_of_stock_event(
                idempotency_key=idempotency_key,
                product_id=product_id,
                sku_id=sku_id,
            )
        except Exception:
            logger.exception("Failed to send SKU_OUT_OF_STOCK to B2C")

    return response


def unreserve_skus(db: Session, order_id: str, items: list[dict]) -> dict:
    normalized = _normalize_items(items)
    payload_for_hash = {
        "order_id": order_id,
        "items": [{"sku_id": str(i["sku_id"]), "quantity": i["quantity"]} for i in normalized],
    }
    req_hash = _request_hash(payload_for_hash)

    existing = db.get(UnreserveOperation, order_id)
    if existing is not None:
        if existing.request_hash != req_hash:
            raise UnreserveConflictError("order_id used with different payload")
        return existing.response

    response: dict = {"ok": True}
    operation = UnreserveOperation(
        order_id=order_id,
        request_hash=req_hash,
        request_payload=payload_for_hash,
        response=response,
    )
    db.add(operation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.get(UnreserveOperation, order_id)
        if existing is None:
            raise UnreserveConflictError("concurrent unreserve request")
        if existing.request_hash != req_hash:
            raise UnreserveConflictError("order_id used with different payload")
        return existing.response

    sku_ids = [i["sku_id"] for i in normalized]
    sku_map = _lock_skus(db, sku_ids)

    for item in normalized:
        sku = sku_map.get(item["sku_id"])
        if sku is None or sku.reserved_quantity < item["quantity"]:
            db.rollback()
            raise UnreserveConflictError("Insufficient reserved quantity")

    for item in normalized:
        sku = sku_map[item["sku_id"]]
        qty = item["quantity"]
        sku.active_quantity += qty
        sku.reserved_quantity -= qty

    db.commit()
    return response
