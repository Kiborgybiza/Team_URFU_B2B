from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx

from src.config import settings

JsonId = UUID | str


class ModerationSenderError(Exception):
    pass


def build_product_created_event(product_id: JsonId, seller_id: str, json_after: dict) -> dict:
    return {
        "event_type": "PRODUCT_CREATED",
        "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-created:{product_id}")),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "product_id": str(product_id),
            "seller_id": seller_id,
            "json_after": json_after,
        },
    }


def build_product_edited_event(product_id: JsonId, seller_id: str, json_after: dict) -> dict:
    return {
        "event_type": "PRODUCT_EDITED",
        "idempotency_key": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "product_id": str(product_id),
            "seller_id": seller_id,
            "json_after": json_after,
        },
    }


def build_product_deleted_event(product_id: JsonId, seller_id: str) -> dict:
    return {
        "event_type": "PRODUCT_DELETED",
        "idempotency_key": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "product_id": str(product_id),
            "seller_id": seller_id,
        },
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


def send_product_created_event(product_id: JsonId, seller_id: str, json_after: dict) -> None:
    _send(build_product_created_event(product_id, seller_id, json_after))


def send_product_edited_event(product_id: JsonId, seller_id: str, json_after: dict) -> None:
    _send(build_product_edited_event(product_id, seller_id, json_after))


def send_product_deleted_event(product_id: JsonId, seller_id: str) -> None:
    _send(build_product_deleted_event(product_id, seller_id))
