import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import ProcessedModerationEvent, Product, ProductStatus
from src.services.b2c_service import send_product_blocked_event
from src.services.errors import NotFoundError

logger = logging.getLogger(__name__)


class ModerationEventIdempotencyConflictError(Exception):
    pass


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(i) for i in value]
    return value


def _request_hash(payload: dict) -> str:
    raw = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _apply_decision(product: Product, payload: dict) -> ProductStatus:
    event_type = payload.get("event_type") or payload.get("status", "")

    if event_type == "MODERATED":
        product.status = ProductStatus.MODERATED
        product.blocking_reason = None
        product.blocking_reason_id = None
        product.moderator_comment = payload.get("moderator_comment")
        product.field_reports = []
        return ProductStatus.MODERATED

    if payload.get("hard_block"):
        product.status = ProductStatus.HARD_BLOCKED
        product.deleted = True
    else:
        product.status = ProductStatus.BLOCKED

    product.blocking_reason = payload.get("blocking_reason")
    product.blocking_reason_id = payload.get("blocking_reason_id")
    product.moderator_comment = payload.get("moderator_comment")
    product.field_reports = payload.get("field_reports", [])
    return product.status


def apply_moderation_event(db: Session, payload: dict) -> dict:
    req_hash = _request_hash(payload)
    idempotency_key = payload["idempotency_key"]

    existing = db.get(ProcessedModerationEvent, idempotency_key)
    if existing is not None:
        if existing.request_hash != req_hash:
            raise ModerationEventIdempotencyConflictError("idempotency_key used with different payload")
        return existing.response

    processed = ProcessedModerationEvent(
        idempotency_key=idempotency_key,
        product_id=payload["product_id"],
        request_hash=req_hash,
        request_payload=_json_safe(payload),
        response={},
    )
    db.add(processed)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.get(ProcessedModerationEvent, idempotency_key)
        if existing is None:
            raise ModerationEventIdempotencyConflictError("concurrent processing")
        if existing.request_hash != req_hash:
            raise ModerationEventIdempotencyConflictError("idempotency_key used with different payload")
        return existing.response

    product = db.get(Product, payload["product_id"])
    if product is None:
        db.rollback()
        raise NotFoundError(f"Product {payload['product_id']} not found")

    resulting_status = _apply_decision(product, payload)
    response: dict = {
        "ok": True,
        "product_id": str(product.id),
        "status": resulting_status.value,
    }
    processed.response = response
    db.commit()

    event_type = payload.get("event_type") or payload.get("status", "")
    if event_type == "BLOCKED":
        try:
            send_product_blocked_event(
                idempotency_key=idempotency_key,
                product_id=product.id,
            )
        except Exception:
            logger.exception("Failed to send PRODUCT_BLOCKED to B2C")

    return response
