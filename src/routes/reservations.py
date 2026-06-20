import uuid

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config import settings
from src.database import get_db
from src.services.reservation_service import (
    IdempotencyConflictError,
    ReservationConflictError,
    UnreserveConflictError,
    reserve_skus,
    unreserve_skus,
)

router = APIRouter(tags=["Reservations"])


def _error(code: int, err_code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"code": err_code, "message": message})


def _require_b2c_key(x_service_key: str | None) -> JSONResponse | None:
    if not x_service_key or x_service_key != settings.b2c_to_b2b_key:
        return JSONResponse(status_code=401, content={"code": "UNAUTHORIZED", "message": "Authorization required"})
    return None


class ReserveItem(BaseModel):
    sku_id: uuid.UUID
    quantity: int = Field(ge=1)


class ReserveRequest(BaseModel):
    idempotency_key: str
    items: list[ReserveItem]


class UnreserveItem(BaseModel):
    sku_id: uuid.UUID
    quantity: int = Field(ge=1)


class UnreserveRequest(BaseModel):
    order_id: str
    items: list[UnreserveItem]


@router.post("/api/v1/reserve", status_code=status.HTTP_200_OK)
def reserve_endpoint(
    payload: ReserveRequest,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
):
    auth_err = _require_b2c_key(x_service_key)
    if auth_err:
        return auth_err

    items = [{"sku_id": item.sku_id, "quantity": item.quantity} for item in payload.items]
    try:
        result = reserve_skus(db, payload.idempotency_key, items)
    except IdempotencyConflictError as exc:
        return _error(409, "IDEMPOTENCY_CONFLICT", str(exc))
    except ReservationConflictError as exc:
        return JSONResponse(status_code=409, content={"code": "INSUFFICIENT_STOCK", **exc.response})

    return result


@router.post("/api/v1/unreserve", status_code=status.HTTP_200_OK)
def unreserve_endpoint(
    payload: UnreserveRequest,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
):
    auth_err = _require_b2c_key(x_service_key)
    if auth_err:
        return auth_err

    items = [{"sku_id": item.sku_id, "quantity": item.quantity} for item in payload.items]
    try:
        result = unreserve_skus(db, payload.order_id, items)
    except UnreserveConflictError as exc:
        return _error(409, "UNRESERVE_CONFLICT", str(exc))

    return result
