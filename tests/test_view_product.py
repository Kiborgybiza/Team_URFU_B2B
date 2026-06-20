"""US-B2B-03: View product — GET /api/v1/products/{id}"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.models import Product, ProductCharacteristic, ProductImage, ProductStatus, SKU

SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
OTHER_SELLER_ID = "d4e5f6a7-b8c9-0123-defa-234567890123"


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create(
        *,
        seller_id: str = SELLER_ID,
        status: ProductStatus = ProductStatus.MODERATED,
        blocking_reason: dict | None = None,
        field_reports: list | None = None,
    ) -> Product:
        category = category_factory()
        product = Product(
            title="iPhone 15 Pro Max",
            description="Flagship smartphone",
            seller_id=seller_id,
            category_id=category.id,
            status=status,
            blocking_reason=blocking_reason,
            field_reports=field_reports or [],
        )
        product.images = [ProductImage(url="/s3/iphone15.jpg", ordering=0)]
        product.characteristics = [ProductCharacteristic(name="Brand", value="Apple")]
        db_session.add(product)
        db_session.flush()

        sku = SKU(
            product_id=product.id,
            name="256GB Black",
            price=12999000,
            cost_price=8000000,
            discount=0,
            image="/s3/iphone15-black.jpg",
            active_quantity=5,
            reserved_quantity=2,
        )
        db_session.add(sku)
        db_session.commit()
        db_session.refresh(product)
        return product

    return create


def test_get_moderated_product_returns_full_payload(client, auth_headers, product_factory):
    """Seller gets full product data including cost_price for MODERATED product."""
    product = product_factory(status=ProductStatus.MODERATED)

    response = client.get(
        f"/api/v1/products/{product.id}",
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(product.id)
    assert body["status"] == "MODERATED"
    assert body["title"] == "iPhone 15 Pro Max"
    assert len(body["skus"]) == 1
    sku = body["skus"][0]
    assert sku["cost_price"] is not None
    assert body["blocking_reason"] is None


def test_get_blocked_product_returns_blocking_reason_and_field_reports(client, auth_headers, category_factory, db_session):
    """BLOCKED product returns blocking_reason and field_reports."""
    blocking = {
        "id": str(uuid4()),
        "title": "Некорректное описание",
        "code": "WRONG_DESC",
        "comment": "Описание не соответствует товару",
    }
    field_reports = [
        {"field_name": "description", "sku_id": None, "comment": "Текст скопирован"}
    ]

    category = category_factory()
    product = Product(
        title="Test Product",
        description="Description",
        seller_id=SELLER_ID,
        category_id=category.id,
        status=ProductStatus.BLOCKED,
        blocking_reason=blocking,
        field_reports=field_reports,
    )
    product.images = [ProductImage(url="/s3/test.jpg", ordering=0)]
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    response = client.get(
        f"/api/v1/products/{product.id}",
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["blocking_reason"] is not None
    assert body["blocking_reason"]["title"] == "Некорректное описание"
    assert len(body["field_reports"]) == 1


def test_get_others_product_returns_404(client, auth_headers, product_factory):
    """Accessing another seller's product must return 404 (not 403)."""
    product = product_factory(seller_id=OTHER_SELLER_ID)

    response = client.get(
        f"/api/v1/products/{product.id}",
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 404


def test_get_nonexistent_returns_404(client, auth_headers):
    """Non-existent product ID must return 404."""
    response = client.get(
        f"/api/v1/products/{uuid4()}",
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
