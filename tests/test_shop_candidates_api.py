from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog import shop_candidates as candidate_module
from stroyhub.catalog.shop_candidates import CandidateDiscoverySeed, ShopCandidateCatalog
from stroyhub.core.config import settings

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
    session.execute(
        text("TRUNCATE shop_source_candidates, shops, shop_identities RESTART IDENTITY CASCADE")
    )

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


def test_shop_source_candidate_api_lists_candidates(
    client: TestClient,
    db_session: Session,
) -> None:
    ShopCandidateCatalog(db_session).refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="candidate-api-list",
                display_name="Candidate API",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
    )

    response = client.get("/shop-source-candidates")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "id": response.json()["items"][0]["id"],
            "source": "2gis",
            "source_id": "candidate-api-list",
            "source_type": "2gis",
            "display_name": "Candidate API",
            "address": "Yakutsk",
            "website_url": None,
            "rubrics": "Стройматериалы",
            "status": "pending",
            "has_products": True,
            "has_prices": True,
            "has_website": True,
            "product_count": 0,
            "priced_product_count": 0,
            "priority": 100,
            "priority_reason": "есть цены и сайт",
            "last_seen_at": response.json()["items"][0]["last_seen_at"],
            "last_checked_at": response.json()["items"][0]["last_checked_at"],
            "missing_since": None,
            "approved_shop_id": None,
        }
    ]


def test_shop_source_candidate_api_refresh_uses_twogis_discovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovered = [
        CandidateDiscoverySeed(
            source_id="discovered-api",
            display_name="Discovered API",
            address="Yakutsk",
            rubrics="Стройматериалы",
            has_prices_signal=True,
            has_website_signal=True,
        )
    ]

    monkeypatch.setattr(candidate_module, "discover_twogis_candidates", lambda: discovered)
    response = client.post("/shop-source-candidates/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["checked"] == len(discovered)
    assert payload["created"] == len(discovered)
    assert payload["skipped_approved"] == 0
    assert payload["items"][0]["priority"] == 100
    assert payload["items"][0]["has_prices"] is True


def test_shop_source_candidate_api_approves_candidate(
    client: TestClient,
    db_session: Session,
) -> None:
    ShopCandidateCatalog(db_session).refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="candidate-api-approve",
                display_name="Approve API",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
            )
        ],
    )
    candidate_id = client.get("/shop-source-candidates").json()["items"][0]["id"]

    response = client.post(f"/shop-source-candidates/{candidate_id}/approve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["approved_shop_id"] is not None
    assert client.get("/shop-source-candidates").json() == {"items": []}
    approved = client.get("/shop-source-candidates", params={"include_approved": True}).json()
    assert approved["items"][0]["source_id"] == "candidate-api-approve"
