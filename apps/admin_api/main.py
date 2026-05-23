from fastapi import FastAPI
from stroyhub import __version__

from apps.admin_api.canonical_products import router as canonical_products_router
from apps.admin_api.categories import router as categories_router
from apps.admin_api.matches import router as matches_router
from apps.admin_api.operations import router as operations_router
from apps.admin_api.product_matches import router as product_matches_router
from apps.admin_api.product_normalization import router as product_normalization_router
from apps.admin_api.products import router as products_router
from apps.admin_api.scrapes import router as scrapes_router
from apps.admin_api.shop_candidates import router as shop_candidates_router
from apps.admin_api.shops import identity_router
from apps.admin_api.shops import router as shops_router


def create_app() -> FastAPI:
    app = FastAPI(title="StroyHub Admin API", version=__version__)
    app.include_router(canonical_products_router)
    app.include_router(categories_router)
    app.include_router(matches_router)
    app.include_router(product_normalization_router)
    app.include_router(product_matches_router)
    app.include_router(products_router)
    app.include_router(operations_router)
    app.include_router(scrapes_router)
    app.include_router(shop_candidates_router)
    app.include_router(shops_router)
    app.include_router(identity_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
