from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import Shop, ShopIdentity

import scripts.seed_unicom_source as seed_unicom_source


def test_seed_unicom_source_dry_run_lists_official_source(capsys) -> None:  # type: ignore[no-untyped-def]
    result = seed_unicom_source.main(
        ["--dry-run", "--category-uuid", "category-a", "--categories-per-run", "10"]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "schedule shop: source=unicom" in output
    assert "source_type=official_api" in output
    assert "category_uuids=1" in output
    assert "categories_per_run=10" in output


def test_seed_unicom_source_can_discover_leaf_categories(
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    class FakeUnicomClient:
        def fetch_leaf_category_uuids(self) -> tuple[str, ...]:
            return ("leaf-a", "leaf-b", "leaf-c")

    monkeypatch.setattr(seed_unicom_source, "UnicomClient", FakeUnicomClient)

    result = seed_unicom_source.main(["--dry-run", "--discover-categories"])

    output = capsys.readouterr().out
    assert result == 0
    assert "category_uuids=3" in output


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 1})

    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not available")

    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def test_seed_unicom_source_preserves_existing_scrape_metadata(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(seed_unicom_source, "UNICOM_SOURCE", "unicom_seed_test")
    monkeypatch.setattr(seed_unicom_source, "UNICOM_DEFAULT_SHOP_SOURCE_ID", "uc-seed-test")
    monkeypatch.setattr(seed_unicom_source, "UNICOM_DEFAULT_SHOP_NAME", "Юником Seed Test")

    scraped_at = datetime(2026, 5, 17, 1, 0, tzinfo=UTC)
    next_scrape_at = datetime(2026, 5, 18, 0, 0, tzinfo=UTC)
    ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom_seed_test",
            source_id="uc-seed-test",
            source_type="official_api",
            name="Old Unicom",
            last_scraped_at=scraped_at,
            next_scrape_at=next_scrape_at,
            scrape_status="failed",
            error_count=2,
            raw={"last_scrape_error": "timeout"},
        )
    )
    existing_identity = ShopIdentity(
        display_name="Юником Seed Test",
        preferred_source="2gis",
        website_url="https://old.example.test/",
    )
    db_session.add(existing_identity)
    db_session.commit()

    try:
        result = seed_unicom_source.main(
            [
                "--category-uuid",
                "category-a",
                "--category-uuid",
                "category-b",
                "--limit",
                "25",
                "--max-pages",
                "4",
            ]
        )

        db_session.expire_all()
        seeded = db_session.scalar(
            select(Shop).where(
                Shop.source == "unicom_seed_test",
                Shop.source_id == "uc-seed-test",
            )
        )
        identity = db_session.scalar(
            select(ShopIdentity).where(ShopIdentity.preferred_source == "unicom_seed_test")
        )
        assert result == 0
        assert seeded is not None
        assert identity is not None
        assert identity.id == existing_identity.id
        assert seeded.shop_identity_id == identity.id
        assert identity.website_url == "https://old.example.test/"
        assert seeded.name == "Юником Seed Test"
        assert seeded.source_type == "official_api"
        assert seeded.last_scraped_at == scraped_at
        assert seeded.next_scrape_at == next_scrape_at
        assert seeded.scrape_status == "failed"
        assert seeded.error_count == 2
        assert seeded.raw == {
            "source": "unicom_seed_test",
            "source_type": "official_api",
            "category_uuids": ["category-a", "category-b"],
            "category_discovery": "explicit_or_default",
            "categories_per_run": 50,
            "limit": 25,
            "max_pages": 4,
            "sort": "popular",
            "pacing": "sequential categories; no concurrent requests",
            "unicom_category_batch": {
                "enabled": False,
                "total": 2,
                "next_index": 0,
                "categories_seen": 0,
                "categories_per_run": 50,
                "completed": False,
                "category_product_counts": {},
                "total_products": None,
                "last_stop_reason": None,
            },
            "last_scrape_error": "timeout",
        }
    finally:
        db_session.query(Shop).filter(
            Shop.source == "unicom_seed_test",
            Shop.source_id == "uc-seed-test",
        ).delete(synchronize_session=False)
        db_session.query(ShopIdentity).filter(
            ShopIdentity.preferred_source == "unicom_seed_test"
        ).delete(
            synchronize_session=False
        )
        db_session.commit()
