import uuid

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config import settings
from src.database import get_db
from src.services.product_service import get_catalog_products, get_product_by_id
from src.services.errors import NotFoundError

router = APIRouter(prefix="/api/v1/public/products", tags=["Public Catalog"])


def _require_service_key(x_service_key: str | None = Header(default=None, alias="X-Service-Key")) -> JSONResponse | None:
    if not x_service_key or x_service_key != settings.b2c_to_b2b_key:
        return JSONResponse(status_code=401, content={"code": "UNAUTHORIZED", "message": "Authorization required"})
    return None


def _image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _char_out(c) -> dict:
    return {"id": str(c.id), "name": c.name, "value": c.value}


def _sku_image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _sku_public_out(sku) -> dict:
    return {
        "id": str(sku.id),
        "product_id": str(sku.product_id),
        "name": sku.name,
        "price": sku.price,
        "discount": sku.discount,
        "article": sku.article,
        "images": [_sku_image_out(i) for i in sku.images],
        "active_quantity": sku.active_quantity,
        "stock_quantity": sku.active_quantity + sku.reserved_quantity,
        "characteristics": [_char_out(c) for c in sku.characteristics],
    }


def _product_short_out(product) -> dict:
    """Short catalog card per openapi ProductPublicShortResponse.

    required: [id, title, slug, status, category_id, created_at, min_price]
    """
    visible_skus = [s for s in product.skus if not s.deleted and s.active_quantity > 0]
    priced = [s.price for s in (visible_skus or [s for s in product.skus if not s.deleted])]
    return {
        "id": str(product.id),
        "title": product.title,
        "slug": product.slug or "",
        "status": product.status.value,
        "category_id": str(product.category_id),
        "min_price": min(priced) if priced else 0,
        "cover_image": product.images[0].url if product.images else None,
        "created_at": product.created_at.isoformat(),
    }


def _product_public_out(product) -> dict:
    return {
        "id": str(product.id),
        "seller_id": str(product.seller_id),
        "category_id": str(product.category_id),
        "title": product.title,
        "description": product.description,
        "slug": product.slug,
        "status": product.status.value,
        "category": {"id": str(product.category.id), "name": product.category.name},
        "images": [_image_out(i) for i in product.images],
        "characteristics": [_char_out(c) for c in product.characteristics],
        "skus": [_sku_public_out(s) for s in product.skus if not s.deleted and s.active_quantity > 0],
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.get("", status_code=status.HTTP_200_OK)
def list_public_products(
    ids: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    min_price: int | None = Query(default=None),
    max_price: int | None = Query(default=None),
    auth_error: JSONResponse | None = Depends(_require_service_key),
    db: Session = Depends(get_db),
):
    if auth_error is not None:
        return auth_error

    products = get_catalog_products(db, ids)
    total_count = len(products)
    page = products[offset: offset + limit]
    return {
        "items": [_product_short_out(p) for p in page],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
    }


class BatchRequest(BaseModel):
    product_ids: list[str]


@router.post("/batch", status_code=status.HTTP_200_OK)
def batch_public_products(
    payload: BatchRequest,
    auth_error: JSONResponse | None = Depends(_require_service_key),
    db: Session = Depends(get_db),
):
    if auth_error is not None:
        return auth_error

    ids_str = ",".join(payload.product_ids)
    products = get_catalog_products(db, ids_str if ids_str else None)
    return [_product_public_out(p) for p in products]
