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
from stroyhub.scraping import runner as scrape_runner

import apps.worker.tasks as worker_tasks
import scripts.scrape_shop_sources as scrape_shop_sources


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


def test_scrape_due_shops_passes_source_type_filter(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    repository = ShopRepository(db_session)
    unicom_shop = repository.upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-due-source-type-unicom",
            source_type="official_api",
            name="Unicom Source Type Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    db_session.commit()
    scheduled_shop_ids: list[int] = []
    observed_kwargs: dict[str, object] = {}

    def fake_list_due_shops(*args: object, **kwargs: object) -> list[Shop]:
        observed_kwargs.update(kwargs)
        return [unicom_shop]

    monkeypatch.setattr(worker_tasks.scrape_shop, "delay", scheduled_shop_ids.append)
    monkeypatch.setattr(worker_tasks, "list_due_shops", fake_list_due_shops)

    try:
        result = worker_tasks.scrape_due_shops.run(source_type="official_api", limit=5)

        assert result["scheduled"] == 1
        assert result["source_type"] == "official_api"
        assert observed_kwargs["source_type"] == "official_api"
        assert observed_kwargs["limit"] == 5
        assert scheduled_shop_ids == [unicom_shop.id]
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_due_shops_rejects_manual_source_type() -> None:
    with pytest.raises(ValueError, match="unsupported source_type"):
        worker_tasks.scrape_due_shops.run(source_type="manual")


def test_scrape_shop_skips_disabled_source_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="worker-disabled-2gis",
            source_type="2gis",
            name="Disabled 2GIS",
            scrape_status="disabled",
        )
    )
    db_session.commit()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("disabled source should not be scraped")

    monkeypatch.setattr(scrape_runner, "scrape_twogis_branch", fail_if_called)

    try:
        result = worker_tasks.scrape_shop.run(shop.id)

        assert result == {
            "shop_id": shop.id,
            "source": "2gis",
            "source_type": "2gis",
            "status": "skipped",
            "reason": "source_disabled",
        }
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_marks_source_running_before_scraping(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-running-unicom",
            source_type="official_api",
            name="Running Unicom",
            raw={"category_uuids": ["category-a"]},
        )
    )
    db_session.commit()
    observed_statuses: list[str] = []

    def fake_scrape_unicom_shop(*args: object, **kwargs: object) -> SimpleNamespace:
        db_session.expire(shop)
        observed_statuses.append(shop.scrape_status)
        assert isinstance(shop.raw, dict)
        assert "last_scrape_started_at" in shop.raw
        return SimpleNamespace(
            scrape_status="success",
            products_seen=0,
            source_products_saved=0,
            price_snapshots_saved=0,
            batch_progress=False,
        )

    monkeypatch.setattr(scrape_runner, "scrape_unicom_shop", fake_scrape_unicom_shop)

    try:
        result = worker_tasks.scrape_shop.run(shop.id)

        assert observed_statuses == ["running"]
        assert result["status"] == "success"
        db_session.expire(shop)
        assert shop.scrape_status == "success"
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_shop_skips_duplicate_running_source_without_live_network(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-already-running-unicom",
            source_type="official_api",
            name="Already Running Unicom",
            scrape_status="running",
        )
    )
    db_session.commit()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("running source should not be scraped twice")

    monkeypatch.setattr(scrape_runner, "scrape_unicom_shop", fail_if_called)

    try:
        result = worker_tasks.scrape_shop.run(shop.id)

        assert result == {
            "shop_id": shop.id,
            "source": "unicom",
            "source_type": "official_api",
            "status": "skipped",
            "reason": "scrape_already_running",
        }
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_source_controls_cli_enqueues_due_source_type(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    repository = ShopRepository(db_session)
    unicom_shop = repository.upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-cli-due-unicom",
            source_type="official_api",
            name="CLI Unicom Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    repository.upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="worker-cli-due-metalltorg",
            source_type="official_html",
            name="CLI Metalltorg Due",
            next_scrape_at=now - timedelta(minutes=1),
        )
    )
    db_session.commit()
    scheduled_shop_ids: list[int] = []
    monkeypatch.setattr(
        scrape_shop_sources.worker_tasks.scrape_shop,
        "delay",
        scheduled_shop_ids.append,
    )
    observed_filters: dict[str, object] = {}

    def fake_list_due_shops(*args: object, **kwargs: object) -> list[Shop]:
        observed_filters.update(kwargs)
        return [unicom_shop]

    monkeypatch.setattr(scrape_shop_sources, "list_due_shops", fake_list_due_shops)

    try:
        exit_code = scrape_shop_sources.main(["due", "--source-type", "official_api"])

        output = capsys.readouterr().out
        assert exit_code == 0
        assert observed_filters["source_type"] == "official_api"
        assert scheduled_shop_ids == [unicom_shop.id]
        assert "source_type=official_api" in output
        assert "shops_scheduled=1" in output
        assert "CLI Unicom Due" in output
        assert "CLI Metalltorg Due" not in output
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_source_controls_cli_skips_disabled_shop(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="worker-cli-disabled-2gis",
            source_type="2gis",
            name="CLI Disabled 2GIS",
            scrape_status="disabled",
        )
    )
    db_session.commit()
    scheduled_shop_ids: list[int] = []
    monkeypatch.setattr(
        scrape_shop_sources.worker_tasks.scrape_shop,
        "delay",
        scheduled_shop_ids.append,
    )

    try:
        exit_code = scrape_shop_sources.main(["shop", "--shop-id", str(shop.id)])

        output = capsys.readouterr().out
        assert exit_code == 0
        assert scheduled_shop_ids == []
        assert "status=skipped" in output
        assert "reason=source_disabled" in output
    finally:
        _delete_worker_test_shops(db_session)


def test_scrape_source_controls_cli_reports_partial_sync_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="unicom",
            source_id="worker-cli-partial-unicom",
            source_type="official_api",
            name="CLI Partial Unicom",
            raw={"category_uuids": ["category-a"]},
        )
    )
    db_session.commit()

    def fake_scrape_shop(shop_id: int) -> dict[str, object]:
        return {
            "shop_id": shop_id,
            "source": "unicom",
            "source_type": "official_api",
            "status": "partial",
            "products_seen": 100,
            "products_saved": 90,
            "price_snapshots_saved": 90,
        }

    monkeypatch.setattr(scrape_shop_sources.worker_tasks.scrape_shop, "run", fake_scrape_shop)

    try:
        exit_code = scrape_shop_sources.main(["shop", "--shop-id", str(shop.id), "--sync"])

        output = capsys.readouterr().out
        assert exit_code == 1
        assert "mode=sync" in output
        assert "status=partial" in output
        assert "products_seen=100" in output
        assert "price_snapshots_saved=90" in output
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

    monkeypatch.setattr(scrape_runner, "scrape_unicom_shop", fake_scrape_unicom_shop)

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

    monkeypatch.setattr(scrape_runner, "scrape_unicom_shop", fake_scrape_unicom_shop)

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

    monkeypatch.setattr(scrape_runner, "scrape_metalltorg_shop", fake_scrape_metalltorg_shop)

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

    monkeypatch.setattr(scrape_runner, "scrape_metalltorg_shop", fake_scrape_metalltorg_shop)

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
                        "worker-due-source-type-unicom",
                        "worker-disabled-2gis",
                        "worker-running-unicom",
                        "worker-already-running-unicom",
                        "worker-cli-due-unicom",
                        "worker-cli-due-metalltorg",
                        "worker-cli-disabled-2gis",
                        "worker-cli-partial-unicom",
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
