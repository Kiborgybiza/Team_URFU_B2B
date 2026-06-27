"""US-B2B-02: Add SKU — POST /api/v1/skus"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.models import Product, ProductImage, ProductStatus

SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeModerationResponse:
    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def moderation_requests(monkeypatch):
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append({"url": url, "json": json, "headers": headers})
        return FakeModerationResponse()

    monkeypatch.setattr("src.services.moderation_service.httpx.post", fake_post)
    return requests


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create(*, seller_id: str = SELLER_ID, status: ProductStatus = ProductStatus.CREATED) -> Product:
        category = category_factory()
        product = Product(
            title="iPhone 15",
            description="Flagship phone",
            seller_id=seller_id,
            category_id=category.id,
            status=status,
        )
        product.images = [ProductImage(url="/s3/phone.jpg", ordering=0)]
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        return product

    return create


def sku_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": str(product_id),
        "name": "256GB Black",
        "price": 12999000,
        "discount": 0,
        "images": [{"url": "/s3/iphone15-black.jpg", "ordering": 0}],
        "characteristics": [{"name": "Color", "value": "Black"}],
    }
    payload.update(overrides)
    return payload


def test_first_sku_transitions_product_to_on_moderation(client, auth_headers, product_factory, moderation_requests, db_session):
    """First SKU on a CREATED product triggers ON_MODERATION status."""
    product = product_factory(status=ProductStatus.CREATED)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION


def test_first_sku_emits_created_event_to_moderation(client, auth_headers, product_factory, moderation_requests):
    """First SKU sends PRODUCT_CREATED event to Moderation with correct fields."""
    product = product_factory(status=ProductStatus.CREATED)

    client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert len(moderation_requests) == 1
    event = moderation_requests[0]["json"]
    assert event["event_type"] == "PRODUCT_CREATED"
    assert "idempotency_key" in event
    assert "occurred_at" in event
    assert event["payload"]["product_id"] == str(product.id)
    assert "json_after" in event["payload"]


def test_second_sku_no_state_change(client, auth_headers, product_factory, moderation_requests, db_session):
    """Adding a second SKU does not change product status and does not emit event."""
    product = product_factory(status=ProductStatus.ON_MODERATION)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 0


def test_add_sku_to_hard_blocked_returns_403(client, auth_headers, product_factory):
    """Adding SKU to a HARD_BLOCKED product must return 403."""
    product = product_factory(status=ProductStatus.HARD_BLOCKED)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "FORBIDDEN"


def test_add_sku_unauthorized_returns_401(client, product_factory):
    """No Authorization header must return 401."""
    product = product_factory()

    response = client.post("/api/v1/skus", json=sku_payload(product.id))
    assert response.status_code == 401


def test_add_sku_without_image_returns_400(client, auth_headers, product_factory, moderation_requests):
    """SKU without any image must return 400 with INVALID_REQUEST."""
    product = product_factory(status=ProductStatus.CREATED)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id, images=[], image=None),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert "image" in body["message"].lower()
    assert len(moderation_requests) == 0


def test_sku_on_moderated_product_retriggers_moderation(client, auth_headers, product_factory, moderation_requests, db_session):
    """Adding SKU to MODERATED product transitions it to ON_MODERATION and sends PRODUCT_EDITED event."""
    product = product_factory(status=ProductStatus.MODERATED)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    event = moderation_requests[0]["json"]
    assert event["event_type"] == "PRODUCT_EDITED"
    assert event["payload"]["product_id"] == str(product.id)
    assert "json_before" in event["payload"]
    assert "json_after" in event["payload"]


def test_sku_on_blocked_product_retriggers_moderation(client, auth_headers, product_factory, moderation_requests, db_session):
    """Adding SKU to BLOCKED product transitions it to ON_MODERATION and sends PRODUCT_EDITED event."""
    product = product_factory(status=ProductStatus.BLOCKED)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    event = moderation_requests[0]["json"]
    assert event["event_type"] == "PRODUCT_EDITED"
    assert event["payload"]["product_id"] == str(product.id)
