from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import Shop, ShopIdentity

import scripts.seed_metalltorg_source as seed_metalltorg_source


def test_seed_metalltorg_source_dry_run_lists_official_source(capsys) -> None:  # type: ignore[no-untyped-def]
    result = seed_metalltorg_source.main(["--dry-run", "--category-url", "https://example.test/"])

    output = capsys.readouterr().out
    assert result == 0
    assert "schedule shop: source=metalltorg" in output
    assert "source_type=official_html" in output
    assert "category_urls=1" in output


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


def test_seed_metalltorg_source_preserves_existing_scrape_metadata(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(seed_metalltorg_source, "METALLTORG_SOURCE", "metalltorg_seed_test")
    monkeypatch.setattr(
        seed_metalltorg_source,
        "METALLTORG_SHOP_SOURCE_ID",
        "metalltorg-seed-test",
    )
    monkeypatch.setattr(
        seed_metalltorg_source,
        "METALLTORG_DEFAULT_SHOP_NAME",
        "Металл Торг Seed Test",
    )

    scraped_at = datetime(2026, 5, 18, 1, 0, tzinfo=UTC)
    next_scrape_at = datetime(2026, 5, 19, 0, 0, tzinfo=UTC)
    ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg_seed_test",
            source_id="metalltorg-seed-test",
            source_type="official_html",
            name="Old Metalltorg",
            last_scraped_at=scraped_at,
            next_scrape_at=next_scrape_at,
            scrape_status="failed",
            error_count=2,
            raw={"last_scrape_error": "timeout"},
        )
    )
    existing_identity = ShopIdentity(
        display_name="Металл Торг Seed Test",
        preferred_source="2gis",
        website_url="https://old.example.test/",
    )
    db_session.add(existing_identity)
    db_session.commit()

    try:
        result = seed_metalltorg_source.main(
            [
                "--category-url",
                "https://example.test/catalog/kirpich/",
                "--max-pages",
                "2",
                "--timeout",
                "3.5",
            ]
        )

        db_session.expire_all()
        seeded = db_session.scalar(
            select(Shop).where(
                Shop.source == "metalltorg_seed_test",
                Shop.source_id == "metalltorg-seed-test",
            )
        )
        identity = db_session.scalar(
            select(ShopIdentity).where(ShopIdentity.preferred_source == "metalltorg_seed_test")
        )
        assert result == 0
        assert seeded is not None
        assert identity is not None
        assert identity.id == existing_identity.id
        assert seeded.shop_identity_id == identity.id
        assert identity.website_url == "https://old.example.test/"
        assert seeded.source_type == "official_html"
        assert seeded.last_scraped_at == scraped_at
        assert seeded.next_scrape_at == next_scrape_at
        assert seeded.scrape_status == "failed"
        assert seeded.error_count == 2
        assert seeded.raw == {
            "source": "metalltorg_seed_test",
            "source_type": "official_html",
            "category_urls": ["https://example.test/catalog/kirpich/"],
            "max_pages": 2,
            "timeout": 3.5,
            "pacing": "sequential pages and categories; no concurrent requests",
            "selector_health": "brittle_html",
            "last_scrape_error": "timeout",
        }
    finally:
        db_session.query(Shop).filter(
            Shop.source == "metalltorg_seed_test",
            Shop.source_id == "metalltorg-seed-test",
        ).delete(synchronize_session=False)
        db_session.query(ShopIdentity).filter(
            ShopIdentity.preferred_source == "metalltorg_seed_test"
        ).delete(synchronize_session=False)
        db_session.commit()
