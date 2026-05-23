from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog import shop_candidates as candidate_module
from stroyhub.catalog.shop_candidates import CandidateDiscoverySeed, ShopCandidateCatalog
from stroyhub.core.config import settings
from stroyhub.db import ShopIdentityCreate, ShopIdentityRepository
from stroyhub.models import Shop

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
            "official_strategy": None,
            "official_source_shop_id": None,
            "official_source_status": None,
            "official_source_last_scraped_at": None,
            "suggested_identity": None,
            "scrape_result": None,
        }
    ]
    assert response.json()["groups"] == []


def test_shop_source_candidate_api_exposes_official_strategy(
    client: TestClient,
    db_session: Session,
) -> None:
    ShopCandidateCatalog(db_session).refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="7037402698889811",
                display_name="Металл Торг",
                address="Проспект Михаила Николаева, 1",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
    )

    response = client.get("/shop-source-candidates")

    assert response.status_code == 200
    assert response.json()["items"][0]["official_strategy"] == {
        "source": "metalltorg",
        "source_type": "official_html",
        "label": "Металл Торг HTML",
        "status": "implemented",
    }
    assert response.json()["groups"][0]["key"] == "official:metalltorg"
    assert response.json()["groups"][0]["candidate_ids"] == [response.json()["items"][0]["id"]]


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
    monkeypatch: pytest.MonkeyPatch,
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
    observed_shop_ids: list[int] = []

    def fake_enqueue_shop_scrape(shop_id: int) -> dict[str, object]:
        observed_shop_ids.append(shop_id)
        return {
            "shop_id": shop_id,
            "status": "queued",
            "task_id": "task-2gis",
        }

    monkeypatch.setattr("apps.api.shop_candidates.enqueue_shop_scrape", fake_enqueue_shop_scrape)
    monkeypatch.setattr(
        "stroyhub.catalog.shop_candidates._resolve_candidate_website",
        lambda source_id: "https://candidate.example.test/",
    )
    monkeypatch.setattr(
        "stroyhub.catalog.official_sources._discover_unicom_category_uuids",
        lambda: ("category-a", "category-b", "category-c"),
    )

    response = client.post(f"/shop-source-candidates/{candidate_id}/approve")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["approved_shop_id"] is not None
    assert observed_shop_ids == [payload["approved_shop_id"]]
    assert payload["scrape_result"] == {
        "shop_id": payload["approved_shop_id"],
        "status": "queued",
        "task_id": "task-2gis",
    }
    assert client.get("/shop-source-candidates").json() == {"items": [], "groups": []}
    approved = client.get("/shop-source-candidates", params={"include_approved": True}).json()
    assert approved["items"][0]["source_id"] == "candidate-api-approve"


def test_shop_source_candidate_api_suggests_identity_and_approves_branch(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Металл Торг", address="Якутск")
    )
    ShopCandidateCatalog(db_session).refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="candidate-api-branch",
                display_name="Металлторг",
                address="Проспект Михаила Николаева, 1",
                rubrics="Стройматериалы",
                has_prices_signal=True,
            )
        ],
    )

    candidate = client.get("/shop-source-candidates").json()["items"][0]

    assert candidate["suggested_identity"] == {
        "id": identity.id,
        "display_name": "Металл Торг",
        "status": "active",
        "source_count": 0,
        "reason": "name_match",
    }
    monkeypatch.setattr(
        "apps.api.shop_candidates.enqueue_shop_scrape",
        lambda shop_id: {"shop_id": shop_id, "status": "queued"},
    )

    response = client.post(
        f"/shop-source-candidates/{candidate['id']}/approve",
        json={"shop_identity_id": identity.id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    shop = db_session.get(Shop, response.json()["approved_shop_id"])
    assert shop is not None
    assert shop.shop_identity_id == identity.id


def test_shop_source_candidate_api_materializes_official_strategy(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ShopCandidateCatalog(db_session).refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="7037402698746785",
                display_name="Юником",
                address="Вилюйский тракт 3 километр, 1/4",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
    )
    observed_shop_ids: list[int] = []

    def fake_enqueue_shop_scrape(shop_id: int) -> dict[str, object]:
        observed_shop_ids.append(shop_id)
        return {
            "shop_id": shop_id,
            "status": "queued",
            "task_id": "task-unicom",
        }

    monkeypatch.setattr("apps.api.shop_candidates.enqueue_shop_scrape", fake_enqueue_shop_scrape)
    monkeypatch.setattr(
        "stroyhub.catalog.official_sources._discover_unicom_category_uuids",
        lambda: ("category-a", "category-b", "category-c"),
    )

    response = client.post(
        "/shop-source-candidates/official-strategies/unicom/materialize",
        json={"run_scrape": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "unicom"
    assert payload["shop"]["source"] == "unicom"
    assert payload["shop"]["source_type"] == "official_api"
    assert payload["identity"]["preferred_source"] == "unicom"
    assert payload["related_candidate_ids"]
    assert observed_shop_ids == [payload["shop"]["id"]]
    assert payload["scrape_result"] == {
        "shop_id": payload["shop"]["id"],
        "status": "queued",
        "task_id": "task-unicom",
    }
    assert client.get("/shop-source-candidates").json()["items"][0]["status"] == "pending"
