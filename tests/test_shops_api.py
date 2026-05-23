from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopRepository,
    ShopUpsert,
)

from apps.admin_api.main import create_app
from apps.admin_api.products import get_session


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


def test_shops_endpoint_lists_shops_without_raw_payload(
    client: TestClient, db_session: Session
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(
            display_name="API Identity",
            preferred_source="2gis",
            status="active",
            notes="not exposed through shop row",
        )
    )
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="2gis",
            source_id="shops-api-1",
            source_type="2gis",
            name="API Shop",
            shop_identity_id=identity.id,
            address="Yakutsk, Test Street 1",
            url="https://example.test/shop",
            raw={"secret": "not exposed"},
            scrape_status="ok",
            error_count=3,
            last_scraped_at=datetime(2026, 5, 17, 8, 30, tzinfo=UTC),
            next_scrape_at=datetime(2026, 5, 18, 0, 0, tzinfo=UTC),
        )
    )

    response = client.get("/shops", params={"source": "2gis", "status": "ok"})

    assert response.status_code == 200
    items = response.json()["items"]
    item = next(item for item in items if item["id"] == shop.id)
    assert item == {
        "id": shop.id,
        "shop_identity_id": identity.id,
        "identity": {
            "id": identity.id,
            "display_name": "API Identity",
            "status": "active",
            "preferred_source": "2gis",
        },
        "source": "2gis",
        "source_id": "shops-api-1",
        "source_type": "2gis",
        "name": "API Shop",
        "address": "Yakutsk, Test Street 1",
        "url": "https://example.test/shop",
        "scrape_status": "ok",
        "last_scraped_at": "2026-05-17T08:30:00Z",
        "next_scrape_at": "2026-05-18T00:00:00Z",
        "scrape_interval": 86400,
        "error_count": 3,
        "is_preferred_source": True,
        "twogis_large_catalog": None,
        "enqueue_failed": None,
    }
    assert "raw" not in item


def test_shops_endpoint_filters_by_source_and_status(
    client: TestClient, db_session: Session
) -> None:
    shops = ShopRepository(db_session)
    matching = shops.upsert(
        ShopUpsert(
            source="unicom",
            source_id="shops-api-2",
            name="Matching Shop",
            scrape_status="failed",
        )
    )
    other_source = shops.upsert(
        ShopUpsert(
            source="2gis",
            source_id="shops-api-3",
            name="Other Source Shop",
            scrape_status="failed",
        )
    )
    other_status = shops.upsert(
        ShopUpsert(
            source="unicom",
            source_id="shops-api-4",
            name="Other Status Shop",
            scrape_status="ok",
        )
    )

    response = client.get("/shops", params={"source": "unicom", "status": "failed"})

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()["items"]}
    assert matching.id in returned_ids
    assert other_source.id not in returned_ids
    assert other_status.id not in returned_ids


def test_shops_endpoint_filters_by_source_type_and_identity_relationship(
    client: TestClient, db_session: Session
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Linked", preferred_source="unicom")
    )
    shops = ShopRepository(db_session)
    linked = shops.upsert(
        ShopUpsert(
            source="unicom",
            source_id="shops-api-linked",
            source_type="official_api",
            name="Linked Official",
            shop_identity_id=identity.id,
        )
    )
    shops.upsert(
        ShopUpsert(
            source="2gis",
            source_id="shops-api-unlinked",
            source_type="2gis",
            name="Unlinked 2GIS",
        )
    )

    response = client.get(
        "/shops",
        params={
            "source_type": "official_api",
            "identity_id": identity.id,
            "identity": "linked",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [linked.id]
    assert response.json()["items"][0]["is_preferred_source"] is True


def test_shops_endpoint_handles_empty_results(client: TestClient) -> None:
    response = client.get(
        "/shops",
        params={"source": "source-with-no-shops", "status": "failed"},
    )

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_shops_endpoint_rejects_unknown_status_filter(client: TestClient) -> None:
    response = client.get("/shops", params={"status": "not-a-real-status"})
    assert response.status_code == 422


def test_shop_identity_endpoints_create_update_link_and_unlink_sources(
    client: TestClient, db_session: Session
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="shops-api-metalltorg",
            source_type="official_html",
            name="Metalltorg",
        )
    )

    create_response = client.post(
        "/shop-identities",
        json={
            "display_name": "Металл Торг",
            "website_url": "https://metalltorg.biz/catalog/",
            "preferred_source": "metalltorg",
            "status": "active",
            "notes": "official source first",
            "locked_fields": {"display_name": True},
        },
    )

    assert create_response.status_code == 201
    identity = create_response.json()
    assert identity["display_name"] == "Металл Торг"
    assert identity["preferred_source"] == "metalltorg"
    assert identity["source_count"] == 0

    link_response = client.post(f"/shop-identities/{identity['id']}/sources/{shop.id}")

    assert link_response.status_code == 200
    linked_shop = link_response.json()
    assert linked_shop["shop_identity_id"] == identity["id"]
    assert linked_shop["identity"]["display_name"] == "Металл Торг"
    assert linked_shop["is_preferred_source"] is True

    update_response = client.patch(
        f"/shop-identities/{identity['id']}",
        json={
            "display_name": "Ignored because locked",
            "status": "hold",
            "notes": "temporarily paused",
        },
    )

    assert update_response.status_code == 200
    updated_identity = update_response.json()
    assert updated_identity["display_name"] == "Металл Торг"
    assert updated_identity["status"] == "hold"
    assert updated_identity["source_count"] == 1

    list_response = client.get("/shop-identities", params={"status": "hold"})

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["items"]] == [identity["id"]]

    unlink_response = client.delete(f"/shops/{shop.id}/identity")

    assert unlink_response.status_code == 200
    assert unlink_response.json()["shop_identity_id"] is None
    assert unlink_response.json()["identity"] is None

    relink_response = client.post(f"/shop-identities/{identity['id']}/sources/{shop.id}")
    assert relink_response.status_code == 200

    delete_response = client.delete(f"/shop-identities/{identity['id']}")
    assert delete_response.status_code == 204
    remaining_identities = client.get("/shop-identities").json()["items"]
    assert identity["id"] not in {item["id"] for item in remaining_identities}
    remaining_shops = client.get("/shops").json()["items"]
    target_shop = next(item for item in remaining_shops if item["id"] == shop.id)
    assert target_shop["shop_identity_id"] is None


def test_shop_identity_api_rejects_manual_source_boundary(client: TestClient) -> None:
    response = client.post(
        "/shop-identities",
        json={"display_name": "Manual", "preferred_source": "manual"},
    )

    assert response.status_code == 400
    assert "manual is not an accepted shop source" in response.json()["detail"]


def test_retry_shop_scrape_marks_source_scheduled_and_enqueues_task(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="shops-api-retry",
            source_type="official_html",
            name="Retry Metalltorg",
            scrape_status="failed",
            error_count=1,
        )
    )
    enqueued_shop_ids: list[int] = []

    def fake_enqueue_shop_scrape(shop_id: int) -> dict[str, object]:
        enqueued_shop_ids.append(shop_id)
        return {"shop_id": shop_id, "status": "queued", "task_id": "retry-task"}

    monkeypatch.setattr("apps.admin_api.shops.enqueue_shop_scrape", fake_enqueue_shop_scrape)

    response = client.post(f"/shops/{shop.id}/scrape/retry")

    assert response.status_code == 200
    assert response.json() == {
        "shop_id": shop.id,
        "source": "metalltorg",
        "source_type": "official_html",
        "status": "queued",
        "task_id": "retry-task",
        "reason": None,
    }
    assert enqueued_shop_ids == [shop.id]
    assert shop.scrape_status == "scheduled"
    assert shop.next_scrape_at is not None


def test_retry_shop_scrape_retries_scheduled_shop_with_enqueue_failure(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="shops-api-retry-enqueue-failed",
            source_type="official_html",
            name="Retry Enqueue Failed",
            scrape_status="scheduled",
            raw={
                "enqueue_failed": {
                    "operation": "shop_retry",
                    "failed_at": "2026-05-23T10:00:00+00:00",
                    "reason": "redis unavailable",
                }
            },
        )
    )

    monkeypatch.setattr(
        "apps.admin_api.shops.enqueue_shop_scrape",
        lambda shop_id: {"shop_id": shop_id, "status": "queued", "task_id": "retry-task"},
    )

    response = client.post(f"/shops/{shop.id}/scrape/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    db_session.expire(shop)
    assert shop.raw is None or "enqueue_failed" not in shop.raw


def test_retry_shop_scrape_rejects_running_source(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="shops-api-running-retry",
            source_type="official_html",
            name="Running Metalltorg",
            scrape_status="running",
        )
    )
    monkeypatch.setattr(
        "apps.admin_api.shops.enqueue_shop_scrape",
        lambda shop_id: pytest.fail(f"unexpected enqueue for shop {shop_id}"),
    )

    response = client.post(f"/shops/{shop.id}/scrape/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "shop scrape is already running"


def test_retry_shop_scrape_returns_503_when_enqueue_fails(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(
            source="metalltorg",
            source_id="shops-api-enqueue-fail",
            source_type="official_html",
            name="Enqueue Fail Shop",
            scrape_status="failed",
        )
    )
    monkeypatch.setattr(
        "apps.admin_api.shops.enqueue_shop_scrape",
        lambda shop_id: {
            "shop_id": shop_id,
            "status": "enqueue_failed",
            "reason": "redis unavailable",
        },
    )

    response = client.post(f"/shops/{shop.id}/scrape/retry")

    assert response.status_code == 503
    assert response.json()["detail"] == "redis unavailable"
    db_session.expire(shop)
    assert isinstance(shop.raw, dict)
    enqueue_failed = shop.raw.get("enqueue_failed")
    assert isinstance(enqueue_failed, dict)
    assert enqueue_failed["operation"] == "shop_retry"
    assert enqueue_failed["reason"] == "redis unavailable"
    shops = client.get("/shops", params={"source": "metalltorg"}).json()["items"]
    item = next(item for item in shops if item["id"] == shop.id)
    assert item["enqueue_failed"]["operation"] == "shop_retry"
    assert item["enqueue_failed"]["reason"] == "redis unavailable"
