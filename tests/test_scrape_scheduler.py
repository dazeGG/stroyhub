from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.scraping.scheduler import (
    list_due_shops,
    mark_shop_scrape_completion,
    mark_shop_scrape_failure,
    next_failed_scrape_at,
    next_successful_scrape_at,
)

from apps.worker.celery_app import celery_app


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 1})

    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not available")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_shop_repository_lists_due_shops_without_disabled_shops(db_session: Session) -> None:
    now = datetime(2026, 5, 17, 15, 0, tzinfo=UTC)
    repository = ShopRepository(db_session)
    source = "scheduler-test"
    due = repository.upsert(
        ShopUpsert(
            source=source,
            source_id="due-shop",
            name="Due Shop",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    repository.upsert(
        ShopUpsert(
            source=source,
            source_id="future-shop",
            name="Future Shop",
            next_scrape_at=now + timedelta(minutes=1),
        )
    )
    repository.upsert(
        ShopUpsert(
            source=source,
            source_id="disabled-shop",
            name="Disabled Shop",
            next_scrape_at=now - timedelta(minutes=1),
            scrape_status="disabled",
        )
    )

    due_shops = list_due_shops(db_session, now=now, source=source)

    assert [shop.id for shop in due_shops] == [due.id]


def test_scheduler_calculates_success_and_failure_next_scrape_times() -> None:
    scraped_at = datetime(2026, 5, 17, 15, 0, tzinfo=UTC)

    assert next_successful_scrape_at(
        completed_at=scraped_at,
        scrape_interval=86400,
    ) == datetime(2026, 5, 18, 15, 0, tzinfo=UTC)
    assert next_failed_scrape_at(
        failed_at=scraped_at,
        scrape_interval=86400,
        error_count=3,
    ) == datetime(2026, 5, 21, 15, 0, tzinfo=UTC)


def test_scheduler_marks_success_and_failure_with_backoff(db_session: Session) -> None:
    now = datetime(2026, 5, 17, 15, 0, tzinfo=UTC)
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="backoff-shop",
            name="Backoff Shop",
            scrape_interval=86400,
            error_count=2,
        )
    )

    mark_shop_scrape_completion(shop, completed_at=now, scrape_status="success")

    assert shop.scrape_status == "success"
    assert shop.error_count == 0
    assert shop.next_scrape_at == now + timedelta(days=1)

    mark_shop_scrape_failure(shop, failed_at=now, error="timeout")

    assert shop.scrape_status == "failed"
    assert shop.error_count == 1
    assert shop.next_scrape_at == now + timedelta(days=1)
    assert shop.raw == {"last_scrape_error": "timeout"}


def test_scheduler_reschedules_batch_progress_after_fifteen_minutes(
    db_session: Session,
) -> None:
    now = datetime(2026, 5, 17, 15, 0, tzinfo=UTC)
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="batch-shop",
            name="Batch Shop",
            scrape_interval=86400,
        )
    )

    mark_shop_scrape_completion(
        shop,
        completed_at=now,
        scrape_status="partial",
        partial_is_progress=True,
    )

    assert shop.scrape_status == "partial"
    assert shop.error_count == 0
    assert shop.next_scrape_at == now + timedelta(minutes=15)


def test_scheduler_reschedules_large_sources_weekly(db_session: Session) -> None:
    now = datetime(2026, 5, 17, 15, 0, tzinfo=UTC)
    repository = ShopRepository(db_session)
    twogis_shop = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="large-2gis-shop",
            name="Large 2GIS Shop",
            scrape_interval=86400,
            raw={"twogis_large_catalog": {"total": 5001}},
        )
    )
    unicom_shop = repository.upsert(
        ShopUpsert(
            source="unicom",
            source_id="large-unicom-shop",
            name="Large Unicom Shop",
            scrape_interval=86400,
            raw={"unicom_category_batch": {"total_products": 5001}},
        )
    )

    mark_shop_scrape_completion(twogis_shop, completed_at=now, scrape_status="success")
    mark_shop_scrape_completion(unicom_shop, completed_at=now, scrape_status="success")

    assert twogis_shop.next_scrape_at == now + timedelta(days=7)
    assert unicom_shop.next_scrape_at == now + timedelta(days=7)


def test_celery_beat_runs_due_shop_dispatcher_every_fifteen_minutes() -> None:
    schedule = celery_app.conf.beat_schedule["scrape-due-shops-every-fifteen-minutes"]

    assert celery_app.conf.timezone == "Asia/Yakutsk"
    assert schedule["task"] == "stroyhub.scrape_due_shops"
    assert str(schedule["schedule"]) == "<crontab: */15 * * * * (m/h/dM/MY/d)>"
