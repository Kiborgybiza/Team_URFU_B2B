import uuid

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.config import settings
from src.database import get_db
from src.services.errors import NotFoundError
from src.services.moderation_event_service import (
    ModerationEventIdempotencyConflictError,
    apply_moderation_event,
)

router = APIRouter(tags=["Moderation Events"])


def _error(code: int, err_code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"code": err_code, "message": message})


def _require_mod_key(x_service_key: str | None) -> JSONResponse | None:
    if not x_service_key or x_service_key != settings.moderation_to_b2b_key:
        return JSONResponse(status_code=401, content={"code": "UNAUTHORIZED", "message": "Authorization required"})
    return None


class FieldReport(BaseModel):
    field_name: str
    sku_id: str | None = None
    comment: str | None = None


class ModerationEventRequest(BaseModel):
    idempotency_key: str
    product_id: uuid.UUID
    event_type: str
    occurred_at: str | None = None
    moderator_id: str | None = None
    moderator_comment: str | None = None
    hard_block: bool = False
    blocking_reason_id: str | None = None
    field_reports: list[FieldReport] = Field(default_factory=list)


@router.post("/api/v1/moderation/events", status_code=status.HTTP_204_NO_CONTENT)
def moderation_event_endpoint(
    payload: ModerationEventRequest,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
):
    auth_err = _require_mod_key(x_service_key)
    if auth_err:
        return auth_err

    event_payload = {
        "idempotency_key": payload.idempotency_key,
        "product_id": payload.product_id,
        "event_type": payload.event_type,
        "hard_block": payload.hard_block,
        "blocking_reason_id": payload.blocking_reason_id,
        "field_reports": [fr.model_dump() for fr in payload.field_reports],
        "moderator_comment": payload.moderator_comment,
    }

    try:
        apply_moderation_event(db, event_payload)
    except NotFoundError as exc:
        return _error(404, "NOT_FOUND", str(exc))
    except ModerationEventIdempotencyConflictError as exc:
        return _error(409, "IDEMPOTENCY_CONFLICT", str(exc))

    return Response(status_code=204)
