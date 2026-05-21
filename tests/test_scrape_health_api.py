from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import ScrapeRunCreate, ScrapeRunRepository, ShopRepository, ShopUpsert

from apps.api.main import create_app
from apps.api.products import get_session


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


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app = create_app()

    def override_get_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_scrape_health_endpoint_returns_counts_and_recent_runs(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="scrape-health-shop", name="Health Shop")
    )
    repository = ScrapeRunRepository(db_session)
    older = repository.start(
        ScrapeRunCreate(
            source="2gis",
            shop_id=shop.id,
            started_at=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
        )
    )
    repository.finish(
        older,
        status="success",
        items_seen=10,
        items_saved=9,
        finished_at=datetime(2026, 5, 17, 8, 1, tzinfo=UTC),
        raw={"not": "exposed"},
    )
    newer = repository.start(
        ScrapeRunCreate(
            source="2gis",
            shop_id=shop.id,
            started_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )
    repository.finish(
        newer,
        status="failed",
        items_seen=3,
        items_saved=1,
        finished_at=datetime(2026, 5, 17, 9, 1, tzinfo=UTC),
        error="timeout",
        raw={"not": "exposed"},
    )
    other = repository.start(
        ScrapeRunCreate(
            source="unicom",
            shop_id=None,
            started_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
        )
    )
    repository.finish(
        other,
        status="success",
        items_seen=5,
        items_saved=5,
        finished_at=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
    )

    response = client.get(
        "/scrapes/health",
        params={"source": "2gis", "shop": shop.id, "limit": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status_counts"] == [
        {"status": "failed", "count": 1},
        {"status": "success", "count": 1},
    ]
    assert payload["recent_runs"] == [
        {
            "id": newer.id,
            "source": "2gis",
            "shop_id": shop.id,
            "status": "failed",
            "started_at": "2026-05-17T09:00:00Z",
            "finished_at": "2026-05-17T09:01:00Z",
            "items_seen": 3,
            "items_saved": 1,
            "error": "timeout",
        }
    ]
    assert "raw" not in payload["recent_runs"][0]


def test_scrape_health_endpoint_filters_by_status(
    client: TestClient, db_session: Session
) -> None:
    repository = ScrapeRunRepository(db_session)
    success = repository.start(
        ScrapeRunCreate(
            source="2gis",
            status="success",
            started_at=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
        )
    )
    failed = repository.start(
        ScrapeRunCreate(
            source="2gis",
            status="failed",
            started_at=datetime(2026, 5, 17, 9, 0, tzinfo=UTC),
        )
    )

    response = client.get("/scrapes/health", params={"status": "failed"})

    assert response.status_code == 200
    assert payload_ids(response) == [failed.id]
    assert success.id not in payload_ids(response)


def test_scrape_health_endpoint_handles_empty_results(client: TestClient) -> None:
    response = client.get("/scrapes/health", params={"source": "missing-source"})

    assert response.status_code == 200
    assert response.json() == {"status_counts": [], "recent_runs": []}


def payload_ids(response: object) -> list[int]:
    return [item["id"] for item in response.json()["recent_runs"]]
