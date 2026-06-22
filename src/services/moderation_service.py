from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx

from src.config import settings

JsonId = UUID | str


class ModerationSenderError(Exception):
    pass


def build_product_created_event(product_id: JsonId, seller_id: str) -> dict:
    return {
        "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-created:{product_id}")),
        "product_id": str(product_id),
        "seller_id": seller_id,
        "event_type": "CREATED",
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_product_edited_event(product_id: JsonId, seller_id: str) -> dict:
    return {
        "idempotency_key": str(uuid4()),
        "product_id": str(product_id),
        "seller_id": seller_id,
        "event_type": "EDITED",
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_product_deleted_event(product_id: JsonId, seller_id: str) -> dict:
    return {
        "idempotency_key": str(uuid4()),
        "product_id": str(product_id),
        "seller_id": seller_id,
        "event_type": "DELETED",
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _send(payload: dict) -> None:
    url = f"{settings.moderation_url.rstrip('/')}/api/v1/b2b/events"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"X-Service-Key": settings.b2b_to_mod_key},
            timeout=settings.moderation_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ModerationSenderError("Moderation service unavailable") from exc


def send_product_created_event(product_id: JsonId, seller_id: str) -> None:
    _send(build_product_created_event(product_id, seller_id))


def send_product_edited_event(product_id: JsonId, seller_id: str) -> None:
    _send(build_product_edited_event(product_id, seller_id))


def send_product_deleted_event(product_id: JsonId, seller_id: str) -> None:
    _send(build_product_deleted_event(product_id, seller_id))
