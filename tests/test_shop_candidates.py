from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.shop_candidates import (
    CandidateDiscoverySeed,
    CandidateListFilters,
    ShopCandidateCatalog,
)
from stroyhub.core.config import settings
from stroyhub.db import ShopRepository, ShopUpsert
from stroyhub.models import Shop, ShopSourceCandidate


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


def test_candidate_refresh_prioritizes_prices_then_website(db_session: Session) -> None:
    catalog = ShopCandidateCatalog(db_session)
    seeds = [
        CandidateDiscoverySeed(
            source_id="both",
            display_name="Prices Website",
            address="Yakutsk",
            rubrics="Стройматериалы",
            website_url="https://both.example.test/",
        ),
        CandidateDiscoverySeed(
            source_id="prices",
            display_name="Prices Only",
            address="Yakutsk",
            rubrics="Стройматериалы",
        ),
        CandidateDiscoverySeed(
            source_id="website",
            display_name="Website Only",
            address="Yakutsk",
            rubrics="Стройматериалы",
            website_url="https://website.example.test/",
        ),
        CandidateDiscoverySeed(
            source_id="none",
            display_name="No Prices",
            address="Yakutsk",
            rubrics="Стройматериалы",
        ),
    ]

    summary = catalog.refresh_from_twogis(
        seeds=seeds,
        scraper=_fake_scraper({"both": 2, "prices": 1, "website": 0, "none": 0}),
        refreshed_at=datetime(2026, 5, 23, 1, 0, tzinfo=UTC),
    )
    items = catalog.list_candidates(CandidateListFilters())

    assert summary.checked == 4
    assert summary.created == 4
    assert [item.source_id for item in items] == ["both", "prices", "website", "none"]
    assert [item.priority for item in items] == [100, 80, 60, 10]
    assert items[0].priority_reason == "есть цены и сайт"
    assert items[2].priority_reason == "есть сайт, цен не найдено"
    assert items[3].priority_reason == "цен не найдено"


def test_candidate_refresh_skips_approved_shops_and_marks_missing_stale(
    db_session: Session,
) -> None:
    catalog = ShopCandidateCatalog(db_session)
    first_seen = datetime(2026, 5, 23, 1, 0, tzinfo=UTC)
    second_seen = datetime(2026, 5, 23, 2, 0, tzinfo=UTC)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="will-go-stale",
                display_name="Stale Candidate",
                address="Yakutsk",
                rubrics="Стройматериалы",
            ),
            CandidateDiscoverySeed(
                source_id="approved-source",
                display_name="Approved Candidate",
                address="Yakutsk",
                rubrics="Стройматериалы",
            ),
        ],
        scraper=_fake_scraper({"will-go-stale": 0, "approved-source": 1}),
        refreshed_at=first_seen,
    )
    approved = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="approved-source", name="Approved")
    )

    summary = catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="approved-source",
                display_name="Approved Candidate",
                address="Yakutsk",
                rubrics="Стройматериалы",
            )
        ],
        scraper=_fake_scraper({"approved-source": 1}),
        refreshed_at=second_seen,
    )
    stale = db_session.scalar(
        select(ShopSourceCandidate).where(ShopSourceCandidate.source_id == "will-go-stale")
    )
    approved_candidate = db_session.scalar(
        select(ShopSourceCandidate).where(ShopSourceCandidate.source_id == "approved-source")
    )

    assert summary.skipped_approved == 1
    assert summary.stale == 1
    assert stale is not None
    assert stale.status == "stale"
    assert stale.missing_since == second_seen
    assert approved_candidate is not None
    assert approved_candidate.status == "approved"
    assert approved.id is not None


def test_candidate_refresh_preserves_hidden_and_archived_statuses(
    db_session: Session,
) -> None:
    catalog = ShopCandidateCatalog(db_session)
    seeds = [
        CandidateDiscoverySeed(
            source_id="hidden-source",
            display_name="Hidden Candidate",
            address="Yakutsk",
            rubrics="Стройматериалы",
        ),
        CandidateDiscoverySeed(
            source_id="archived-source",
            display_name="Archived Candidate",
            address="Yakutsk",
            rubrics="Стройматериалы",
        ),
    ]
    catalog.refresh_from_twogis(
        seeds=seeds,
        scraper=_fake_scraper({"hidden-source": 1, "archived-source": 1}),
    )
    hidden = db_session.scalar(
        select(ShopSourceCandidate).where(ShopSourceCandidate.source_id == "hidden-source")
    )
    archived = db_session.scalar(
        select(ShopSourceCandidate).where(ShopSourceCandidate.source_id == "archived-source")
    )
    assert hidden is not None
    assert archived is not None
    hidden.status = "hidden"
    archived.status = "archived"

    catalog.refresh_from_twogis(
        seeds=seeds,
        scraper=_fake_scraper({"hidden-source": 1, "archived-source": 1}),
    )

    assert hidden.status == "hidden"
    assert archived.status == "archived"


def test_candidate_approval_creates_identity_and_tracked_shop(db_session: Session) -> None:
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="approve-me",
                display_name="Approve Me",
                address="Yakutsk",
                rubrics="Стройматериалы",
                website_url="https://approve.example.test/",
            )
        ],
        scraper=_fake_scraper({"approve-me": 1}),
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]

    approved = catalog.approve(candidate.id)
    shop = db_session.scalar(select(Shop).where(Shop.source_id == "approve-me"))

    assert approved.status == "approved"
    assert shop is not None
    assert shop.source == "2gis"
    assert shop.source_type == "2gis"
    assert shop.name == "Approve Me"
    assert shop.url == "https://approve.example.test/"
    assert shop.shop_identity is not None
    assert shop.shop_identity.display_name == "Approve Me"
    assert shop.shop_identity.preferred_source == "2gis"


def _fake_scraper(price_counts: dict[str, int]):  # type: ignore[no-untyped-def]
    def scrape(source_id: str):  # type: ignore[no-untyped-def]
        priced_count = price_counts[source_id]
        products = [SimpleNamespace(price=Decimal("100")) for _ in range(priced_count)]
        if priced_count == 0 and source_id != "none":
            products = [SimpleNamespace(price=None)]
        return SimpleNamespace(
            total=len(products),
            products=products,
            completeness="complete" if products else "empty",
            stop_reason="source_total_reached" if products else "empty_page",
        )

    return scrape
