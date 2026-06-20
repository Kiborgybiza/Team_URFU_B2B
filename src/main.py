from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.routes.products import router as products_router
from src.routes.skus import router as skus_router
from src.services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError

app = FastAPI(title="NeoMarket B2B Service", version="1.0.0")

app.include_router(products_router)
app.include_router(skus_router)


@app.get("/healthz", tags=["Health"])
def healthcheck() -> dict:
    return {"status": "ok"}


@app.exception_handler(NotFoundError)
async def not_found_handler(_, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": str(exc)})


@app.exception_handler(ForbiddenError)
async def forbidden_handler(_, exc: ForbiddenError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"code": "FORBIDDEN", "message": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(_, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "CONFLICT", "message": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(_, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": str(exc)})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = first.get("loc", ())
    field = loc[-1] if loc else "request"
    msg = first.get("msg", "Validation failed")
    return JSONResponse(status_code=400, content={"code": "VALIDATION_ERROR", "message": f"{field}: {msg}"})
