import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Product, ProductCharacteristic, ProductImage, ProductStatus, SKU
from src.services.errors import NotFoundError


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
            selectinload(Product.skus).selectinload(SKU.characteristics),
        )
    )


def get_product_by_id(db: Session, product_id: uuid.UUID, seller_id: uuid.UUID | None = None) -> Product:
    product = db.scalars(_product_query().where(Product.id == product_id)).first()
    if product is None or (seller_id is not None and product.seller_id != seller_id):
        raise NotFoundError(f"Product {product_id} not found")
    return product


def create_product(db: Session, payload: dict, seller_id: uuid.UUID) -> Product:
    if not payload.get("images"):
        raise ProductCreateValidationError("images", "At least one image is required")

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
    )
    product.images = [ProductImage(url=img["url"], ordering=img.get("ordering", 0)) for img in payload["images"]]
    product.characteristics = [
        ProductCharacteristic(name=c["name"], value=c["value"]) for c in payload.get("characteristics", [])
    ]
    db.add(product)
    db.commit()
    return get_product_by_id(db, product.id)
