"""US-B2B-01: Create product — POST /api/v1/products"""
from uuid import uuid4

import pytest

SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
OTHER_SELLER_ID = "d4e5f6a7-b8c9-0123-defa-234567890123"


def product_payload(category_id, **overrides) -> dict:
    payload = {
        "title": "iPhone 15 Pro Max",
        "description": "Flagship smartphone from Apple",
        "category_id": str(category_id),
        "images": [{"url": "/s3/iphone15-front.jpg", "ordering": 0}],
        "characteristics": [{"name": "Brand", "value": "Apple"}],
    }
    payload.update(overrides)
    return payload


def test_create_product_returns_201_with_created_status(client, auth_headers, category_factory):
    """Happy path: product is created with status CREATED and empty skus."""
    category = category_factory()
    response = client.post(
        "/api/v1/products",
        json=product_payload(category.id),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CREATED"
    assert body["title"] == "iPhone 15 Pro Max"
    assert body["skus"] == []
    assert body["id"] is not None
    assert body["deleted"] is False


def test_seller_id_taken_from_jwt(client, auth_headers, category_factory):
    """seller_id in the created product must match the JWT, ignoring any body value."""
    category = category_factory()
    payload = product_payload(category.id)
    payload["seller_id"] = str(uuid4())  # attempt to inject different seller_id

    response = client.post(
        "/api/v1/products",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] == SELLER_ID


def test_missing_images_returns_400(client, auth_headers, category_factory):
    """Request without images must return 400."""
    category = category_factory()
    payload = product_payload(category.id, images=[])

    response = client.post(
        "/api/v1/products",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    body = response.json()
    assert "code" in body


def test_missing_category_returns_400(client, auth_headers):
    """Request without category_id must return 400."""
    payload = {
        "title": "Test product",
        "description": "A description",
        "images": [{"url": "/s3/test.jpg", "ordering": 0}],
    }

    response = client.post(
        "/api/v1/products",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400


def test_invalid_category_id_returns_400(client, auth_headers):
    """Non-existent category_id must return 400."""
    payload = {
        "title": "Test product",
        "description": "A description",
        "category_id": str(uuid4()),
        "images": [{"url": "/s3/test.jpg", "ordering": 0}],
    }

    response = client.post(
        "/api/v1/products",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    body = response.json()
    assert "code" in body


def test_unauthorized_returns_401(client, category_factory):
    """No Authorization header must return 401."""
    category = category_factory()
    payload = {
        "title": "Product",
        "description": "Description",
        "category_id": str(category.id),
        "images": [{"url": "/s3/test.jpg", "ordering": 0}],
    }
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 401
