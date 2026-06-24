import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Product, ProductStatus, SKU, SKUCharacteristic, SKUImage
from src.services.errors import ForbiddenError, NotFoundError
from src.services.moderation_service import ModerationSenderError, send_product_created_event

logger = logging.getLogger(__name__)


class ModerationUnavailableError(Exception):
    pass


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
    image_url = images[0]["url"] if images else payload.get("image") or ""

    is_first_sku = product.status == ProductStatus.CREATED and all(s.deleted for s in product.skus)

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

    if is_first_sku:
        product.status = ProductStatus.ON_MODERATION

    db.flush()

    if is_first_sku:
        try:
            send_product_created_event(product_id=str(product.id), seller_id=str(seller_id))
        except ModerationSenderError as exc:
            db.rollback()
            raise ModerationUnavailableError("Moderation unavailable") from exc

    db.commit()
    return _get_sku(db, sku.id)
