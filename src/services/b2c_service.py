from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from src.config import settings

JsonId = UUID | str


class B2CSenderError(Exception):
    pass


def send_sku_out_of_stock_event(*, idempotency_key: str, product_id: JsonId, sku_id: JsonId) -> None:
    payload = {
        "idempotency_key": idempotency_key,
        "event_type": "SKU_OUT_OF_STOCK",
        "product_id": str(product_id),
        "sku_id": str(sku_id),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    url = f"{settings.b2c_url.rstrip('/')}/api/v1/b2b/events"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"X-Service-Key": settings.b2b_to_b2c_key},
            timeout=settings.b2c_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise B2CSenderError("B2C service unavailable") from exc


def send_product_blocked_event(*, idempotency_key: str, product_id: JsonId) -> None:
    payload = {
        "idempotency_key": idempotency_key,
        "event_type": "PRODUCT_BLOCKED",
        "product_id": str(product_id),
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    url = f"{settings.b2c_url.rstrip('/')}/api/v1/b2b/events"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"X-Service-Key": settings.b2b_to_b2c_key},
            timeout=settings.b2c_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise B2CSenderError("B2C service unavailable") from exc
