import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Product, ProductStatus, SKU, SKUCharacteristic, SKUImage
from src.services.errors import ForbiddenError, NotFoundError
from src.services.moderation_service import ModerationSenderError, send_product_created_event, send_product_edited_event

logger = logging.getLogger(__name__)


class ModerationUnavailableError(Exception):
    pass


class SKUValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _product_snapshot(product: Product) -> dict:
    return {
        "id": str(product.id),
        "seller_id": str(product.seller_id),
        "status": product.status.value,
        "skus": [
            {
                "id": str(s.id),
                "name": s.name,
                "price": s.price,
                "active_quantity": s.active_quantity,
                "cost_price": s.cost_price,
                "reserved_quantity": s.reserved_quantity,
            }
            for s in product.skus
            if not s.deleted
        ],
    }


def _get_product_with_skus(db: Session, product_id: uuid.UUID) -> Product:
    product = db.scalars(
        select(Product).options(selectinload(Product.skus)).where(Product.id == product_id)
    ).first()
    if product is None:
        raise NotFoundError(f"Product {product_id} not found")
    return product


def _get_sku(db: Session, sku_id: uuid.UUID) -> SKU:
    sku = db.scalars(
        select(SKU).options(
            selectinload(SKU.characteristics),
            selectinload(SKU.images),
            selectinload(SKU.product),
        ).where(SKU.id == sku_id)
    ).first()
    if sku is None:
        raise NotFoundError(f"SKU {sku_id} not found")
    return sku


def create_sku(db: Session, payload: dict, seller_id: uuid.UUID) -> SKU:
    product = _get_product_with_skus(db, payload["product_id"])

    if product.seller_id != seller_id:
        raise ForbiddenError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise ForbiddenError("Cannot add SKU to hard-blocked product")

    images = payload.get("images") or []
    image_url = images[0]["url"] if images else payload.get("image") or None
    if not image_url:
        raise SKUValidationError("INVALID_REQUEST", "image is required")

    is_first_sku = product.status == ProductStatus.CREATED and all(s.deleted for s in product.skus)
    needs_remoderation = product.status in (ProductStatus.MODERATED, ProductStatus.BLOCKED)

    # Snapshot "before" must be captured before any changes are applied
    json_before = _product_snapshot(product) if needs_remoderation else None

    sku = SKU(
        product_id=payload["product_id"],
        name=payload["name"],
        price=payload["price"],
        cost_price=payload.get("cost_price"),
        discount=payload.get("discount", 0),
        article=payload.get("article"),
        image=image_url,
        active_quantity=0,
        reserved_quantity=0,
    )
    sku.characteristics = [
        SKUCharacteristic(name=c["name"], value=c["value"]) for c in payload.get("characteristics", [])
    ]
    sku.images = [
        SKUImage(url=img["url"], ordering=img.get("ordering", 0)) for img in images
    ]
    db.add(sku)

    if is_first_sku or needs_remoderation:
        product.status = ProductStatus.ON_MODERATION

    db.flush()

    if is_first_sku:
        try:
            send_product_created_event(
                product_id=str(product.id),
                seller_id=str(seller_id),
                json_after=_product_snapshot(product),
            )
        except ModerationSenderError as exc:
            db.rollback()
            raise ModerationUnavailableError("Moderation unavailable") from exc
    elif needs_remoderation:
        try:
            send_product_edited_event(
                product_id=str(product.id),
                seller_id=str(seller_id),
                json_before=json_before,
                json_after=_product_snapshot(product),
            )
        except ModerationSenderError as exc:
            db.rollback()
            raise ModerationUnavailableError("Moderation unavailable") from exc

    db.commit()
    return _get_sku(db, sku.id)
