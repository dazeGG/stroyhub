"""Database sessions, repositories, and persistence helpers."""

from stroyhub.db.base import Base
from stroyhub.db.session import SessionLocal, engine, get_session

__all__ = [
    "Base",
    "PriceSnapshotCreate",
    "PriceSnapshotRepository",
    "ScrapeRunCreate",
    "ScrapeRunRepository",
    "SessionLocal",
    "ShopRepository",
    "ShopUpsert",
    "SourceProductRepository",
    "SourceProductUpsert",
    "engine",
    "get_session",
]

_REPOSITORY_EXPORTS = {
    "PriceSnapshotCreate",
    "PriceSnapshotRepository",
    "ScrapeRunCreate",
    "ScrapeRunRepository",
    "ShopRepository",
    "ShopUpsert",
    "SourceProductRepository",
    "SourceProductUpsert",
}


def __getattr__(name: str) -> object:
    if name in _REPOSITORY_EXPORTS:
        from stroyhub.db import repositories

        return getattr(repositories, name)

    raise AttributeError(f"module 'stroyhub.db' has no attribute {name!r}")
