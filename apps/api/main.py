from fastapi import FastAPI
from stroyhub import __version__

from apps.api.categories import router as categories_router
from apps.api.matches import router as matches_router
from apps.api.products import router as products_router
from apps.api.scrapes import router as scrapes_router
from apps.api.shop_candidates import router as shop_candidates_router
from apps.api.shops import identity_router
from apps.api.shops import router as shops_router


def create_app() -> FastAPI:
    app = FastAPI(title="StroyHub API", version=__version__)
    app.include_router(categories_router)
    app.include_router(matches_router)
    app.include_router(products_router)
    app.include_router(scrapes_router)
    app.include_router(shop_candidates_router)
    app.include_router(shops_router)
    app.include_router(identity_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
