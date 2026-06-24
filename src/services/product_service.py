import re
import uuid

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Product, ProductCharacteristic, ProductImage, ProductStatus, SKU, SKUImage
from src.services.errors import ForbiddenError, NotFoundError


class ProductCreateValidationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


def _product_query():
    return (
        select(Product)
        .options(
            selectinload(Product.category),
            selectinload(Product.images),
            selectinload(Product.characteristics),
            selectinload(Product.skus).options(
                selectinload(SKU.characteristics),
                selectinload(SKU.images),
            ),
        )
    )


def get_product_by_id(db: Session, product_id: uuid.UUID, seller_id: uuid.UUID | None = None) -> Product:
    product = db.scalars(_product_query().where(Product.id == product_id)).first()
    if product is None or (seller_id is not None and product.seller_id != seller_id):
        raise NotFoundError(f"Product {product_id} not found")
    return product


def get_catalog_products(db: Session, ids_str: str | None = None) -> list[Product]:
    query = _product_query().where(
        and_(Product.status == ProductStatus.MODERATED, Product.deleted == False)  # noqa: E712
    )

    if ids_str:
        try:
            ids = [uuid.UUID(id_s.strip()) for id_s in ids_str.split(",") if id_s.strip()]
        except ValueError:
            ids = []
        if ids:
            query = query.where(Product.id.in_(ids))

    products = db.scalars(query).all()
    return [p for p in products if any(s.active_quantity > 0 for s in p.skus if not s.deleted)]


def update_product(db: Session, product_id: uuid.UUID, payload: dict, seller_id: uuid.UUID) -> Product:
    product = get_product_by_id(db, product_id, seller_id=seller_id)
    if product.status == ProductStatus.HARD_BLOCKED:
        raise ForbiddenError("Cannot edit a hard-blocked product")

    for field in ("title", "description"):
        if field in payload and payload[field] is not None:
            setattr(product, field, payload[field])
    if "category_id" in payload and payload["category_id"] is not None:
        if db.get(Category, payload["category_id"]) is None:
            raise ProductCreateValidationError("category_id", "Category not found")
        product.category_id = payload["category_id"]

    db.commit()
    return get_product_by_id(db, product_id, seller_id=seller_id)


def delete_product(db: Session, product_id: uuid.UUID, seller_id: uuid.UUID) -> None:
    product = get_product_by_id(db, product_id, seller_id=seller_id)
    if product.status == ProductStatus.HARD_BLOCKED:
        raise ForbiddenError("Cannot delete a hard-blocked product")

    product.deleted = True
    db.commit()


def _slugify(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug


def create_product(db: Session, payload: dict, seller_id: uuid.UUID) -> Product:
    category_id = payload.get("category_id")
    if category_id is None:
        raise ProductCreateValidationError("category_id", "category_id is required")
    if db.get(Category, category_id) is None:
        raise ProductCreateValidationError("category_id", "Category not found")

    product = Product(
        title=payload["title"],
        description=payload["description"],
        category_id=category_id,
        seller_id=seller_id,
        status=ProductStatus.CREATED,
        slug=_slugify(payload["title"]),
    )
    product.images = [ProductImage(url=img["url"], ordering=img.get("ordering", 0)) for img in payload["images"]]
    product.characteristics = [
        ProductCharacteristic(name=c["name"], value=c["value"]) for c in payload.get("characteristics", [])
    ]
    db.add(product)
    db.commit()
    return get_product_by_id(db, product.id)
