import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database import get_db
from src.deps import CatalogAccess, CurrentSeller, get_catalog_access, get_current_seller
from src.services.errors import ForbiddenError, NotFoundError
from src.services.product_service import (
    ProductCreateValidationError,
    create_product,
    delete_product,
    get_catalog_products,
    get_product_by_id,
    update_product,
)

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _error(code: int, err_code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"code": err_code, "message": message})


class ImageIn(BaseModel):
    url: str
    ordering: int = 0


class CharacteristicIn(BaseModel):
    name: str
    value: str


class ProductCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category_id: uuid.UUID
    images: list[ImageIn] = Field(default_factory=list, min_length=1)
    characteristics: list[CharacteristicIn] = Field(default_factory=list)


def _image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _char_out(c) -> dict:
    return {"id": str(c.id), "name": c.name, "value": c.value}


def _sku_image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _sku_seller_out(sku) -> dict:
    return {
        "id": str(sku.id),
        "product_id": str(sku.product_id),
        "name": sku.name,
        "price": sku.price,
        "cost_price": sku.cost_price,
        "discount": sku.discount,
        "article": sku.article,
        "images": [_sku_image_out(i) for i in sku.images],
        "active_quantity": sku.active_quantity,
        "reserved_quantity": sku.reserved_quantity,
        "stock_quantity": sku.active_quantity + sku.reserved_quantity,
        "characteristics": [_char_out(c) for c in sku.characteristics],
        "created_at": sku.created_at.isoformat(),
        "updated_at": sku.updated_at.isoformat(),
    }


def _sku_catalog_out(sku) -> dict:
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
        "created_at": sku.created_at.isoformat(),
        "updated_at": sku.updated_at.isoformat(),
    }


def _product_catalog_out(product) -> dict:
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
        "skus": [_sku_catalog_out(s) for s in product.skus if not s.deleted and s.active_quantity > 0],
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


def _product_out(product) -> dict:
    return {
        "id": str(product.id),
        "seller_id": str(product.seller_id),
        "category_id": str(product.category_id),
        "title": product.title,
        "description": product.description,
        "slug": product.slug,
        "status": product.status.value,
        "deleted": product.deleted,
        "blocked": product.blocked,
        "category": {"id": str(product.category.id), "name": product.category.name},
        "images": [_image_out(i) for i in product.images],
        "characteristics": [_char_out(c) for c in product.characteristics],
        "skus": [_sku_seller_out(s) for s in product.skus if not s.deleted],
        "blocking_reason": product.blocking_reason,
        "blocking_reason_id": product.blocking_reason_id,
        "moderator_comment": product.moderator_comment,
        "field_reports": product.field_reports or [],
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


@router.get("", status_code=status.HTTP_200_OK)
def get_catalog_endpoint(
    ids: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    access: CatalogAccess | JSONResponse = Depends(get_catalog_access),
    db: Session = Depends(get_db),
):
    if isinstance(access, JSONResponse):
        return access
    if access.mode != "catalog":
        return _error(401, "UNAUTHORIZED", "Service key required")

    products = get_catalog_products(db, ids)
    total_count = len(products)
    page = products[offset: offset + limit]
    return {
        "items": [_product_catalog_out(p) for p in page],
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{product_id}", status_code=status.HTTP_200_OK)
def get_product_endpoint(
    product_id: uuid.UUID,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        product = get_product_by_id(db, product_id, seller_id=current_seller.seller_id)
    except NotFoundError as exc:
        return _error(404, "NOT_FOUND", str(exc))

    return _product_out(product)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_product_endpoint(
    payload: ProductCreateRequest,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        product = create_product(db, payload.model_dump(), current_seller.seller_id)
    except ProductCreateValidationError as exc:
        return _error(400, "INVALID_REQUEST", f"{exc.field}: {exc.message}")

    return JSONResponse(status_code=201, content=_product_out(product))


class ProductUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category_id: uuid.UUID | None = None


@router.patch("/{product_id}", status_code=status.HTTP_200_OK)
def update_product_endpoint(
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        product = update_product(db, product_id, payload.model_dump(exclude_none=True), current_seller.seller_id)
    except ForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except NotFoundError as exc:
        return _error(404, "NOT_FOUND", str(exc))
    except ProductCreateValidationError as exc:
        return _error(400, "INVALID_REQUEST", f"{exc.field}: {exc.message}")

    return _product_out(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_endpoint(
    product_id: uuid.UUID,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        delete_product(db, product_id, current_seller.seller_id)
    except ForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except NotFoundError as exc:
        return _error(404, "NOT_FOUND", str(exc))

    return Response(status_code=204)
