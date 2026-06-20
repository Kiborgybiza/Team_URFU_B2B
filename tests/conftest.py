import base64
import hashlib
import hmac
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.config import settings
from src.database import Base, get_db
from src.main import app
from src.models import Category


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def category_factory(db_session: Session):
    def create(name: str | None = None) -> Category:
        category = Category(name=name or f"Category-{uuid4()}")
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)
        return category

    return create


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_jwt(seller_id: str) -> str:
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    payload = {"seller_id": seller_id}
    header_raw = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_raw = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_raw}.{payload_raw}".encode("ascii")
    sig = hmac.new(settings.jwt_secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_raw}.{payload_raw}.{_b64encode(sig)}"


@pytest.fixture()
def auth_headers():
    def build(seller_id: str = "c3d4e5f6-a7b8-9012-cdef-123456789012") -> dict:
        return {"Authorization": f"Bearer {make_jwt(seller_id)}"}

    return build


@pytest.fixture()
def service_key_headers():
    return {"X-Service-Key": settings.b2c_to_b2b_key}


@pytest.fixture()
def mod_key_headers():
    return {"X-Service-Key": settings.moderation_to_b2b_key}
