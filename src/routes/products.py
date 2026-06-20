import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database import get_db
from src.deps import CurrentSeller, get_current_seller
from src.services.errors import NotFoundError
from src.services.product_service import ProductCreateValidationError, create_product, get_product_by_id

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
    images: list[ImageIn] = Field(default_factory=list)
    characteristics: list[CharacteristicIn] = Field(default_factory=list)


def _image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _char_out(c) -> dict:
    return {"id": str(c.id), "name": c.name, "value": c.value}


def _sku_seller_out(sku) -> dict:
    return {
        "id": str(sku.id),
        "product_id": str(sku.product_id),
        "name": sku.name,
        "price": sku.price,
        "cost_price": sku.cost_price,
        "discount": sku.discount,
        "article": sku.article,
        "image": sku.image,
        "active_quantity": sku.active_quantity,
        "reserved_quantity": sku.reserved_quantity,
        "stock_quantity": sku.active_quantity + sku.reserved_quantity,
        "characteristics": [_char_out(c) for c in sku.characteristics],
        "created_at": sku.created_at.isoformat(),
        "updated_at": sku.updated_at.isoformat(),
    }


def _product_out(product) -> dict:
    return {
        "id": str(product.id),
        "seller_id": str(product.seller_id),
        "category_id": str(product.category_id),
        "title": product.title,
        "description": product.description,
        "status": product.status.value,
        "deleted": product.deleted,
        "blocked": product.blocked,
        "category": {"id": str(product.category.id), "name": product.category.name},
        "images": [_image_out(i) for i in product.images],
        "characteristics": [_char_out(c) for c in product.characteristics],
        "skus": [_sku_seller_out(s) for s in product.skus if not s.deleted],
        "blocking_reason": product.blocking_reason,
        "field_reports": product.field_reports or [],
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
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
