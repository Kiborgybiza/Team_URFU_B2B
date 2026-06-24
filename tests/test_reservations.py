"""US-B2B-05: Reserve / Unreserve — POST /api/v1/inventory/reserve, POST /api/v1/inventory/unreserve"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.config import settings
from src.models import Product, ProductImage, ProductStatus, SKU

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
def sku_factory(db_session: Session, category_factory):
    def create(*, active_quantity: int = 10, reserved_quantity: int = 0) -> SKU:
        category = category_factory()
        product = Product(
            title="Test Product",
            description="A test product",
            seller_id=SELLER_ID,
            category_id=category.id,
            status=ProductStatus.MODERATED,
        )
        product.images = [ProductImage(url="/s3/test.jpg", ordering=0)]
        db_session.add(product)
        db_session.flush()

        sku = SKU(
            product_id=product.id,
            name="Default SKU",
            price=10000,
            image="/s3/sku.jpg",
            active_quantity=active_quantity,
            reserved_quantity=reserved_quantity,
        )
        db_session.add(sku)
        db_session.commit()
        db_session.refresh(sku)
        return sku

    return create


def reserve_payload(sku_id, quantity: int = 2, idempotency_key: str | None = None, order_id: str | None = None) -> dict:
    return {
        "order_id": order_id or str(uuid4()),
        "idempotency_key": idempotency_key or str(uuid4()),
        "items": [{"sku_id": str(sku_id), "quantity": quantity}],
    }


def test_reserve_all_skus_succeeds(client, service_key_headers, sku_factory, b2c_requests, db_session):
    """Happy path: active_quantity decreases and reserved_quantity increases."""
    sku = sku_factory(active_quantity=10, reserved_quantity=0)
    idem_key = str(uuid4())

    response = client.post(
        "/api/v1/inventory/reserve",
        json=reserve_payload(sku.id, quantity=3, idempotency_key=idem_key),
        headers=service_key_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESERVED"
    assert body["order_id"] is not None
    assert "reserved_at" in body

    db_session.refresh(sku)
    assert sku.active_quantity == 7
    assert sku.reserved_quantity == 3


def test_partial_insufficient_stock_returns_409_all_rollback(client, service_key_headers, sku_factory, b2c_requests, db_session):
    """If one SKU has insufficient stock, all fail — 409 with no changes."""
    sku_ok = sku_factory(active_quantity=10)
    sku_low = sku_factory(active_quantity=1)

    response = client.post(
        "/api/v1/inventory/reserve",
        json={
            "order_id": str(uuid4()),
            "idempotency_key": str(uuid4()),
            "items": [
                {"sku_id": str(sku_ok.id), "quantity": 5},
                {"sku_id": str(sku_low.id), "quantity": 5},
            ],
        },
        headers=service_key_headers,
    )

    assert response.status_code == 409

    db_session.refresh(sku_ok)
    db_session.refresh(sku_low)
    assert sku_ok.active_quantity == 10
    assert sku_low.active_quantity == 1


def test_idempotent_reserve_returns_200_without_double_deduction(client, service_key_headers, sku_factory, b2c_requests, db_session):
    """Repeating the same idempotency_key returns 200 without modifying quantities."""
    sku = sku_factory(active_quantity=10)
    idem_key = str(uuid4())
    payload = reserve_payload(sku.id, quantity=3, idempotency_key=idem_key)

    r1 = client.post("/api/v1/inventory/reserve", json=payload, headers=service_key_headers)
    assert r1.status_code == 200

    r2 = client.post("/api/v1/inventory/reserve", json=payload, headers=service_key_headers)
    assert r2.status_code == 200

    db_session.refresh(sku)
    assert sku.active_quantity == 7
    assert sku.reserved_quantity == 3


def test_sku_out_of_stock_event_emitted(client, service_key_headers, sku_factory, b2c_requests):
    """When active_quantity hits 0, SKU_OUT_OF_STOCK event is sent to B2C."""
    sku = sku_factory(active_quantity=2)
    idem_key = str(uuid4())

    response = client.post(
        "/api/v1/inventory/reserve",
        json=reserve_payload(sku.id, quantity=2, idempotency_key=idem_key),
        headers=service_key_headers,
    )

    assert response.status_code == 200
    assert len(b2c_requests) == 1
    event = b2c_requests[0]["json"]
    assert event["event_type"] == "SKU_OUT_OF_STOCK"
    assert event["sku_id"] == str(sku.id)


def test_unreserve_restores_quantities(client, service_key_headers, sku_factory, b2c_requests, db_session):
    """Unreserve correctly restores active_quantity and reserved_quantity."""
    sku = sku_factory(active_quantity=10)
    order_id = str(uuid4())
    idem_key = str(uuid4())

    client.post(
        "/api/v1/inventory/reserve",
        json=reserve_payload(sku.id, quantity=4, idempotency_key=idem_key, order_id=order_id),
        headers=service_key_headers,
    )
    db_session.refresh(sku)
    assert sku.active_quantity == 6
    assert sku.reserved_quantity == 4

    response = client.post(
        "/api/v1/inventory/unreserve",
        json={"order_id": order_id, "items": [{"sku_id": str(sku.id), "quantity": 4}]},
        headers=service_key_headers,
    )

    assert response.status_code == 200

    db_session.refresh(sku)
    assert sku.active_quantity == 10
    assert sku.reserved_quantity == 0
