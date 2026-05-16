from fastapi import FastAPI
from stroyhub import __version__

from apps.api.products import router as products_router


def create_app() -> FastAPI:
    app = FastAPI(title="StroyHub API", version=__version__)
    app.include_router(products_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
