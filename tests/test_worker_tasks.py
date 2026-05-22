from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import ScrapeRun, Shop

import apps.worker.tasks as worker_tasks


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


def test_scrape_due_shops_schedules_supported_sources(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    repository = ShopRepository(db_session)
    twogis_shop = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="worker-due-2gis",
            name="2GIS Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    unicom_shop = repository.upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-due-unicom",
            source_type="official_api",
            name="Unicom Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    metalltorg_shop = repository.upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="worker-due-metalltorg",
            source_type="official_html",
            name="Metalltorg Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    unsupported_shop = repository.upsert(
        ShopUpsert(
            source="unsupported-worker",
            source_id="worker-due-unsupported",
            name="Unsupported Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    db_session.commit()
    scheduled_shop_ids: list[int] = []
    monkeypatch.setattr(worker_tasks.scrape_shop, "delay", scheduled_shop_ids.append)
    monkeypatch.setattr(
        worker_tasks,
        "list_due_shops",
        lambda *args, **kwargs: [twogis_shop, unicom_shop, metalltorg_shop, unsupported_shop],
    )

    try:
        result = worker_tasks.scrape_due_shops.run(limit=10)

        assert result["scheduled"] == 3
        assert scheduled_shop_ids == [twogis_shop.id, unicom_shop.id, metalltorg_shop.id]
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_runs_unicom_source_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-unicom-shop",
            source_type="official_api",
            name="Unicom Worker",
            next_scrape_at=datetime.now(UTC) - timedelta(minutes=1),
            raw={"category_uuids": ["category-a"]},
        )
    )
    db_session.commit()

    def fake_scrape_unicom_shop(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            scrape_status="success",
            products_seen=3,
            source_products_saved=3,
            price_snapshots_saved=3,
        )

    monkeypatch.setattr(worker_tasks, "scrape_unicom_shop", fake_scrape_unicom_shop)

    try:
        result = worker_tasks.scrape_shop.run(shop.id)
        db_session.expire_all()
        refreshed_shop = db_session.get(Shop, shop.id)

        assert result["source"] == "unicom"
        assert result["status"] == "success"
        assert result["products_seen"] == 3
        assert refreshed_shop is not None
        assert refreshed_shop.scrape_status == "success"
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_records_unicom_failure_run(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-unicom-failure",
            source_type="official_api",
            name="Unicom Failure",
            raw={"category_uuids": ["category-a"]},
        )
    )
    db_session.commit()

    def fake_scrape_unicom_shop(*args: object, **kwargs: object) -> SimpleNamespace:
        raise RuntimeError("source timeout")

    monkeypatch.setattr(worker_tasks, "scrape_unicom_shop", fake_scrape_unicom_shop)

    try:
        with pytest.raises(RuntimeError, match="source timeout"):
            worker_tasks.scrape_shop.run(shop.id)

        db_session.expire_all()
        refreshed_shop = db_session.get(Shop, shop.id)
        failure_run = db_session.scalar(
            select(ScrapeRun).where(ScrapeRun.shop_id == shop.id, ScrapeRun.status == "failed")
        )
        assert refreshed_shop is not None
        assert refreshed_shop.scrape_status == "failed"
        assert failure_run is not None
        assert failure_run.source == "unicom"
        assert failure_run.error == "source timeout"
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_runs_metalltorg_source_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="worker-metalltorg-shop",
            source_type="official_html",
            name="Metalltorg Worker",
            next_scrape_at=datetime.now(UTC) - timedelta(minutes=1),
            raw={"category_urls": ["https://example.test/catalog/"]},
        )
    )
    db_session.commit()

    def fake_scrape_metalltorg_shop(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            scrape_status="success",
            products_seen=1,
            source_products_saved=1,
            price_snapshots_saved=1,
        )

    monkeypatch.setattr(worker_tasks, "scrape_metalltorg_shop", fake_scrape_metalltorg_shop)

    try:
        result = worker_tasks.scrape_shop.run(shop.id)
        db_session.expire_all()
        refreshed_shop = db_session.get(Shop, shop.id)

        assert result["source"] == "metalltorg"
        assert result["status"] == "success"
        assert result["products_seen"] == 1
        assert refreshed_shop is not None
        assert refreshed_shop.scrape_status == "success"
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_records_metalltorg_failure_run(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="worker-metalltorg-failure",
            source_type="official_html",
            name="Metalltorg Failure",
            raw={"category_urls": ["https://example.test/catalog/"]},
        )
    )
    db_session.commit()

    def fake_scrape_metalltorg_shop(*args: object, **kwargs: object) -> SimpleNamespace:
        raise RuntimeError("selector changed")

    monkeypatch.setattr(worker_tasks, "scrape_metalltorg_shop", fake_scrape_metalltorg_shop)

    try:
        with pytest.raises(RuntimeError, match="selector changed"):
            worker_tasks.scrape_shop.run(shop.id)

        db_session.expire_all()
        refreshed_shop = db_session.get(Shop, shop.id)
        failure_run = db_session.scalar(
            select(ScrapeRun).where(ScrapeRun.shop_id == shop.id, ScrapeRun.status == "failed")
        )
        assert refreshed_shop is not None
        assert refreshed_shop.scrape_status == "failed"
        assert failure_run is not None
        assert failure_run.source == "metalltorg"
        assert failure_run.error == "selector changed"
    finally:
        _delete_worker_test_shops(db_session)


def _delete_worker_test_shops(session: Session) -> None:
    shop_ids = list(
        session.scalars(
            select(Shop.id).where(
                Shop.source_id.in_(
                    [
                        "worker-due-2gis",
                        "worker-due-unicom",
                        "worker-due-metalltorg",
                        "worker-due-unsupported",
                        "worker-unicom-shop",
                        "worker-unicom-failure",
                        "worker-metalltorg-shop",
                        "worker-metalltorg-failure",
                    ]
                )
            )
        )
    )
    if shop_ids:
        session.query(ScrapeRun).filter(ScrapeRun.shop_id.in_(shop_ids)).delete(
            synchronize_session=False
        )
        session.query(Shop).filter(Shop.id.in_(shop_ids)).delete(synchronize_session=False)
        session.commit()
