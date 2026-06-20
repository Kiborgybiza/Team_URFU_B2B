import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Literal
import uuid

from fastapi import Depends, Header
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer

from src.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


@dataclass(frozen=True)
class CurrentSeller:
    seller_id: uuid.UUID


@dataclass(frozen=True)
class CatalogAccess:
    mode: Literal["seller", "catalog"]
    seller_id: uuid.UUID | None = None


def unauthorized_response() -> JSONResponse:
    return JSONResponse(status_code=401, content={"code": "UNAUTHORIZED", "message": "Authorization required"})


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _decode_token(token: str) -> dict[str, Any] | None:
    try:
        header_raw, payload_raw, signature_raw = token.split(".")
        header = json.loads(_b64decode(header_raw))
        if header.get("alg") != settings.jwt_algorithm:
            return None
        signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
        expected = hmac.new(
            settings.jwt_secret_key.encode("utf-8"),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual = _b64decode(signature_raw)
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64decode(payload_raw))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _seller_from_token(token: str | None) -> CurrentSeller | JSONResponse:
    if not token:
        return unauthorized_response()
    payload = _decode_token(token)
    seller_id = payload.get("seller_id") if payload else None
    if not isinstance(seller_id, str) or not seller_id.strip():
        return unauthorized_response()
    try:
        seller_uuid = uuid.UUID(seller_id)
    except ValueError:
        return unauthorized_response()
    return CurrentSeller(seller_id=seller_uuid)


def get_current_seller(token: str | None = Depends(oauth2_scheme)) -> CurrentSeller | JSONResponse:
    return _seller_from_token(token)


def get_catalog_access(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    token: str | None = Depends(oauth2_scheme),
) -> CatalogAccess | JSONResponse:
    if x_service_key is not None:
        if not x_service_key or x_service_key != settings.b2c_to_b2b_key:
            return unauthorized_response()
        return CatalogAccess(mode="catalog")
    current_seller = _seller_from_token(token)
    if isinstance(current_seller, JSONResponse):
        return current_seller
    return CatalogAccess(mode="seller", seller_id=current_seller.seller_id)
