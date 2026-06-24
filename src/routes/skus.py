import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database import get_db
from src.deps import CurrentSeller, get_current_seller
from src.services.errors import ForbiddenError, NotFoundError
from src.services.sku_service import ModerationUnavailableError, create_sku

router = APIRouter(prefix="/api/v1/skus", tags=["SKUs"])


def _error(code: int, err_code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"code": err_code, "message": message})


class ImageIn(BaseModel):
    url: str
    ordering: int = 0


class CharacteristicIn(BaseModel):
    name: str
    value: str


class SKUCreateRequest(BaseModel):
    product_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    price: int = Field(ge=0)
    cost_price: int | None = Field(default=None, ge=0)
    discount: int = Field(default=0, ge=0)
    article: str | None = Field(default=None, max_length=255)
    image: str | None = None
    images: list[ImageIn] = Field(default_factory=list)
    characteristics: list[CharacteristicIn] = Field(default_factory=list)


def _char_out(c) -> dict:
    return {"id": str(c.id), "name": c.name, "value": c.value}


def _sku_image_out(img) -> dict:
    return {"id": str(img.id), "url": img.url, "ordering": img.ordering}


def _sku_out(sku) -> dict:
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


@router.post("", status_code=status.HTTP_201_CREATED)
def create_sku_endpoint(
    payload: SKUCreateRequest,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
):
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        sku = create_sku(db, payload.model_dump(), current_seller.seller_id)
    except ForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except NotFoundError as exc:
        return _error(404, "NOT_FOUND", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")

    return JSONResponse(status_code=201, content=_sku_out(sku))
