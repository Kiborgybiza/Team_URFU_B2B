"""US-B2B-06: Apply moderation — POST /api/v1/events/moderation"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.config import settings
from src.models import Product, ProductCharacteristic, ProductImage, ProductStatus, SKU

SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeB2CResponse:
    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def b2c_requests(monkeypatch):
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers})
        return FakeB2CResponse()

    monkeypatch.setattr("src.services.b2c_service.httpx.post", fake_post)
    return requests


@pytest.fixture()
def moderated_product(db_session: Session, category_factory) -> Product:
    category = category_factory()
    blocking = {"id": str(uuid4()), "title": "Old block", "code": "OLD", "comment": "old comment"}
    product = Product(
        title="iPhone 15",
        description="Great phone",
        seller_id=SELLER_ID,
        category_id=category.id,
        status=ProductStatus.ON_MODERATION,
        blocking_reason=blocking,
        field_reports=[{"field_name": "description", "sku_id": None, "comment": "old report"}],
    )
    product.images = [ProductImage(url="/s3/iphone15.jpg", ordering=0)]
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def moderation_payload(product_id, event_type: str = "MODERATED", **overrides) -> dict:
    payload = {
        "idempotency_key": str(uuid4()),
        "product_id": str(product_id),
        "event_type": event_type,
        "occurred_at": "2026-06-20T12:00:00Z",
        "moderator_id": str(uuid4()),
        "moderator_comment": "OK",
        "hard_block": False,
        "blocking_reason": None,
        "field_reports": [],
    }
    payload.update(overrides)
    return payload


def test_moderated_event_clears_blocking_data(client, mod_key_headers, moderated_product, b2c_requests, db_session):
    """MODERATED event sets product to MODERATED and clears blocking_reason and field_reports."""
    response = client.post(
        "/api/v1/events/moderation",
        json=moderation_payload(moderated_product.id, event_type="MODERATED"),
        headers=mod_key_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "MODERATED"

    db_session.refresh(moderated_product)
    assert moderated_product.status == ProductStatus.MODERATED
    assert moderated_product.blocking_reason is None
    assert moderated_product.field_reports == []
    assert len(b2c_requests) == 0


def test_blocked_soft_saves_field_reports(client, mod_key_headers, moderated_product, b2c_requests, db_session):
    """BLOCKED event with hard_block=False saves BLOCKED status, field_reports, and sends event to B2C."""
    blocking = {"id": str(uuid4()), "title": "Bad images", "code": "BAD_IMAGES", "comment": "Фото низкого качества"}
    field_reports = [{"field_name": "images", "sku_id": None, "comment": "Плохо видно товар"}]

    response = client.post(
        "/api/v1/events/moderation",
        json=moderation_payload(
            moderated_product.id,
            event_type="BLOCKED",
            hard_block=False,
            blocking_reason=blocking,
            field_reports=field_reports,
        ),
        headers=mod_key_headers,
    )

    assert response.status_code == 200

    db_session.refresh(moderated_product)
    assert moderated_product.status == ProductStatus.BLOCKED
    assert moderated_product.blocking_reason is not None
    assert len(moderated_product.field_reports) == 1
    assert len(b2c_requests) == 1
    assert b2c_requests[0]["json"]["event"] == "PRODUCT_BLOCKED"


def test_blocked_hard_sets_terminal_status(client, mod_key_headers, moderated_product, b2c_requests, db_session):
    """BLOCKED event with hard_block=True sets HARD_BLOCKED terminal status and sends B2C event."""
    blocking = {"id": str(uuid4()), "title": "Counterfeit", "code": "COUNTERFEIT", "comment": "Контрафактный товар"}

    response = client.post(
        "/api/v1/events/moderation",
        json=moderation_payload(
            moderated_product.id,
            event_type="BLOCKED",
            hard_block=True,
            blocking_reason=blocking,
            field_reports=[],
        ),
        headers=mod_key_headers,
    )

    assert response.status_code == 200

    db_session.refresh(moderated_product)
    assert moderated_product.status == ProductStatus.HARD_BLOCKED
    assert len(b2c_requests) == 1


def test_hard_blocked_product_rejects_seller_edits(client, auth_headers, mod_key_headers, moderated_product, b2c_requests):
    """PUT and DELETE on a HARD_BLOCKED product must return 403."""
    blocking = {"id": str(uuid4()), "title": "Counterfeit", "code": "COUNTERFEIT", "comment": "Blocked hard"}

    client.post(
        "/api/v1/events/moderation",
        json=moderation_payload(
            moderated_product.id,
            event_type="BLOCKED",
            hard_block=True,
            blocking_reason=blocking,
        ),
        headers=mod_key_headers,
    )

    put_response = client.put(
        f"/api/v1/products/{moderated_product.id}",
        json={"title": "New title"},
        headers=auth_headers(SELLER_ID),
    )
    assert put_response.status_code == 403

    delete_response = client.delete(
        f"/api/v1/products/{moderated_product.id}",
        headers=auth_headers(SELLER_ID),
    )
    assert delete_response.status_code == 403


def test_duplicate_event_same_idempotency_key_no_side_effects(client, mod_key_headers, moderated_product, b2c_requests, db_session):
    """Duplicate event with same idempotency_key returns 200 with no additional changes."""
    idem_key = str(uuid4())
    payload = moderation_payload(moderated_product.id, event_type="MODERATED", idempotency_key=idem_key)

    r1 = client.post("/api/v1/events/moderation", json=payload, headers=mod_key_headers)
    assert r1.status_code == 200

    db_session.refresh(moderated_product)
    assert moderated_product.status == ProductStatus.MODERATED

    r2 = client.post("/api/v1/events/moderation", json=payload, headers=mod_key_headers)
    assert r2.status_code == 200

    db_session.refresh(moderated_product)
    assert moderated_product.status == ProductStatus.MODERATED
    assert len(b2c_requests) == 0


def test_missing_service_key_returns_401(client, moderated_product):
    """Without X-Service-Key, moderation events endpoint returns 401."""
    response = client.post(
        "/api/v1/events/moderation",
        json=moderation_payload(moderated_product.id),
    )
    assert response.status_code == 401
