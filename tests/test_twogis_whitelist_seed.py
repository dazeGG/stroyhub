from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import Shop

from scripts.seed_twogis_whitelist import INITIAL_WHITELIST, main


def test_seed_twogis_whitelist_dry_run_lists_initial_schedule(capsys) -> None:  # type: ignore[no-untyped-def]
    result = main(["--dry-run"])

    output = capsys.readouterr().out
    assert result == 0
    assert len(INITIAL_WHITELIST) == 6
    assert "schedule shop: source=2gis" in output
    assert "scrape_interval=86400" in output


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


def test_seed_twogis_whitelist_preserves_existing_scrape_metadata(
    db_session: Session,
) -> None:
    existing_shop = INITIAL_WHITELIST[0]
    scraped_at = datetime(2026, 5, 17, 1, 0, tzinfo=UTC)
    next_scrape_at = datetime(2026, 5, 18, 0, 0, tzinfo=UTC)
    ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id=existing_shop.branch_id,
            name="Old Name",
            last_scraped_at=scraped_at,
            next_scrape_at=next_scrape_at,
            scrape_status="failed",
            error_count=3,
            raw={"last_scrape_error": "timeout"},
        )
    )
    db_session.commit()

    try:
        result = main([])

        seeded = db_session.scalar(
            select(Shop).where(Shop.source == "2gis", Shop.source_id == existing_shop.branch_id)
        )
        assert result == 0
        assert seeded is not None
        assert seeded.name == existing_shop.name
        assert seeded.last_scraped_at == scraped_at
        assert seeded.next_scrape_at == next_scrape_at
        assert seeded.scrape_status == "failed"
        assert seeded.error_count == 3
        assert seeded.raw == {
            "source": "2gis",
            "branch_id": existing_shop.branch_id,
            "whitelist": "initial",
            "last_scrape_error": "timeout",
        }
    finally:
        db_session.query(Shop).filter(
            Shop.source == "2gis",
            Shop.source_id.in_([shop.branch_id for shop in INITIAL_WHITELIST]),
        ).delete(synchronize_session=False)
        db_session.commit()
