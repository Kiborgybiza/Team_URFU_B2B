"""US-B2B-04: Catalog for B2C — GET /api/v1/products with X-Service-Key"""
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from src.config import settings
from src.models import Product, ProductImage, ProductStatus, SKU

SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create(
        *,
        status: ProductStatus = ProductStatus.MODERATED,
        active_quantity: int = 5,
    ) -> Product:
        category = category_factory()
        product = Product(
            title="Test Product",
            description="A great product",
            seller_id=SELLER_ID,
            category_id=category.id,
            status=status,
        )
        product.images = [ProductImage(url="/s3/test.jpg", ordering=0)]
        db_session.add(product)
        db_session.flush()

        if active_quantity > 0:
            sku = SKU(
                product_id=product.id,
                name="Default",
                price=10000,
                cost_price=5000,
                discount=0,
                image="/s3/test-sku.jpg",
                active_quantity=active_quantity,
                reserved_quantity=0,
            )
            db_session.add(sku)

        db_session.commit()
        db_session.refresh(product)
        return product

    return create


def _assert_no_cost_price(obj):
    if isinstance(obj, dict):
        assert "cost_price" not in obj, f"cost_price found in {obj}"
        assert "reserved_quantity" not in obj, f"reserved_quantity found in {obj}"
        for v in obj.values():
            _assert_no_cost_price(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_cost_price(item)


def test_catalog_returns_moderated_in_stock_products(client, service_key_headers, product_factory):
    """Catalog returns only MODERATED products with active_quantity > 0."""
    moderated = product_factory(status=ProductStatus.MODERATED, active_quantity=3)
    product_factory(status=ProductStatus.BLOCKED, active_quantity=3)
    product_factory(status=ProductStatus.MODERATED, active_quantity=0)

    response = client.get("/api/v1/products", headers=service_key_headers)

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert str(moderated.id) in ids
    assert len(ids) == 1


def test_catalog_excludes_hard_blocked(client, service_key_headers, product_factory):
    """HARD_BLOCKED products must not appear in catalog."""
    product_factory(status=ProductStatus.HARD_BLOCKED, active_quantity=5)
    moderated = product_factory(status=ProductStatus.MODERATED, active_quantity=5)

    response = client.get("/api/v1/products", headers=service_key_headers)

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert str(moderated.id) in ids
    for item_id in ids:
        assert item_id != str(product_factory.__name__)


def test_catalog_missing_service_key_returns_401(client):
    """Without X-Service-Key header, catalog returns 401."""
    response = client.get("/api/v1/products")
    assert response.status_code in (401, 403)


def test_catalog_response_has_no_cost_price(client, service_key_headers, product_factory):
    """Catalog response must not include cost_price or reserved_quantity."""
    product_factory(status=ProductStatus.MODERATED, active_quantity=5)

    response = client.get("/api/v1/products", headers=service_key_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    _assert_no_cost_price(body["items"])


def test_batch_ids_returns_visible_subset(client, service_key_headers, product_factory):
    """?ids= returns only visible products from the given list, no 404 for hidden ones."""
    visible = product_factory(status=ProductStatus.MODERATED, active_quantity=5)
    hidden = product_factory(status=ProductStatus.BLOCKED, active_quantity=5)
    nonexistent_id = str(uuid4())

    params = f"ids={visible.id},{hidden.id},{nonexistent_id}"
    response = client.get(f"/api/v1/products?{params}", headers=service_key_headers)

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body["items"]]
    assert str(visible.id) in ids
    assert str(hidden.id) not in ids
    assert nonexistent_id not in ids


def test_public_products_path_returns_catalog(client, service_key_headers, product_factory):
    """GET /api/v1/public/products items must match ProductPublicShortResponse.

    required: [id, title, slug, status, category_id, created_at, min_price];
    the short card must NOT carry the full-form fields (skus, description, etc.).
    """
    product = product_factory(status=ProductStatus.MODERATED, active_quantity=5)

    response = client.get("/api/v1/public/products", headers=service_key_headers)

    assert response.status_code == 200
    body = response.json()
    assert {"items", "total_count", "limit", "offset"} <= body.keys()

    item = next(i for i in body["items"] if i["id"] == str(product.id))
    for field in ("id", "title", "slug", "status", "category_id", "created_at", "min_price"):
        assert field in item, f"missing required short-card field: {field}"
    assert isinstance(item["min_price"], int)
    assert item["min_price"] == 10000  # factory SKU price
    assert item["cover_image"] == "/s3/test.jpg"  # factory product image

    for full_only in ("skus", "description", "seller_id", "updated_at", "characteristics"):
        assert full_only not in item, f"short card must not include {full_only}"


def test_public_products_path_requires_service_key(client):
    """GET /api/v1/public/products without X-Service-Key returns 401."""
    response = client.get("/api/v1/public/products")
    assert response.status_code == 401


def test_public_products_batch_sku_has_active_quantity(client, service_key_headers, product_factory):
    """Batch (full form) SKU must include active_quantity (no cost_price/reserved_quantity)."""
    product = product_factory(status=ProductStatus.MODERATED, active_quantity=5)

    response = client.post(
        "/api/v1/public/products/batch",
        json={"product_ids": [str(product.id)]},
        headers=service_key_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    sku = body[0]["skus"][0]
    assert "active_quantity" in sku
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku


def test_public_products_canonical_visibility(client, service_key_headers, product_factory):
    """Canonical /api/v1/public/products applies the catalog visibility filter."""
    visible = product_factory(status=ProductStatus.MODERATED, active_quantity=5)
    hard_blocked = product_factory(status=ProductStatus.HARD_BLOCKED, active_quantity=5)
    out_of_stock = product_factory(status=ProductStatus.MODERATED, active_quantity=0)

    response = client.get("/api/v1/public/products", headers=service_key_headers)

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert str(visible.id) in ids
    assert str(hard_blocked.id) not in ids
    assert str(out_of_stock.id) not in ids


def test_public_products_batch_returns_by_ids(client, service_key_headers, product_factory):
    """POST /api/v1/public/products/batch returns visible products for given IDs."""
    visible = product_factory(status=ProductStatus.MODERATED, active_quantity=5)
    hidden = product_factory(status=ProductStatus.BLOCKED, active_quantity=5)

    response = client.post(
        "/api/v1/public/products/batch",
        json={"product_ids": [str(visible.id), str(hidden.id)]},
        headers=service_key_headers,
    )

    assert response.status_code == 200
    body = response.json()
    ids = [item["id"] for item in body]
    assert str(visible.id) in ids
    assert str(hidden.id) not in ids
