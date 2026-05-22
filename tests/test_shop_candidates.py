from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.shop_candidates import (
    CandidateDiscoverySeed,
    CandidateListFilters,
    ShopCandidateCatalog,
    _extract_firm_website,
    parse_twogis_search_candidates,
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


def test_candidate_refresh_prioritizes_prices_then_website(db_session: Session) -> None:
    catalog = ShopCandidateCatalog(db_session)
    seeds = [
        CandidateDiscoverySeed(
            source_id="both",
            display_name="Prices Website",
            address="Yakutsk",
            rubrics="Стройматериалы",
            has_prices_signal=True,
            has_website_signal=True,
        ),
        CandidateDiscoverySeed(
            source_id="prices",
            display_name="Prices Only",
            address="Yakutsk",
            rubrics="Стройматериалы",
            has_prices_signal=True,
        ),
        CandidateDiscoverySeed(
            source_id="website",
            display_name="Website Only",
            address="Yakutsk",
            rubrics="Стройматериалы",
            has_website_signal=True,
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
        refreshed_at=datetime(2026, 5, 23, 1, 0, tzinfo=UTC),
    )
    items = catalog.list_candidates(CandidateListFilters())

    assert summary.checked == 4
    assert summary.created == 4
    assert [item.source_id for item in items] == ["both", "prices", "website", "none"]
    assert [item.priority for item in items] == [100, 80, 60, 10]
    assert items[0].priority_reason == "есть цены и сайт"
    assert items[2].priority_reason == "есть сайт"
    assert items[3].priority_reason == "нет цен и сайта"
    assert [item.product_count for item in items] == [0, 0, 0, 0]


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
    )

    assert hidden.status == "hidden"
    assert archived.status == "archived"


def test_candidate_approval_creates_unlinked_tracked_shop(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = ShopCandidateCatalog(db_session)
    monkeypatch.setattr(
        "stroyhub.catalog.shop_candidates._resolve_candidate_website",
        lambda source_id: f"https://{source_id}.example.test/",
    )
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="approve-me",
                display_name="Approve Me",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]

    approved = catalog.approve(candidate.id)
    shop = db_session.scalar(select(Shop).where(Shop.source_id == "approve-me"))

    assert approved.status == "approved"
    assert shop is not None
    assert shop.source == "2gis"
    assert shop.source_type == "2gis"
    assert shop.name == "Approve Me"
    assert shop.url == "https://approve-me.example.test/"
    assert shop.shop_identity_id is None
    assert shop.shop_identity is None


def test_parse_twogis_search_candidates_extracts_real_search_cards() -> None:
    page_html = """
    <div>
      <a href="/yakutsk/firm/70000001007229923" class="_1rehek">
        <span class="_lvwrwt"><span>Евролайн</span></span>
      </a>
      <div>
        Магазин строительных материалов Улица Курнатовского, 86,
        Якутск Стройматериалы · Доставка
      </div>
      <a href="/yakutsk/firm/7037402698889811" class="_1rehek">
        <span class="_lvwrwt"><span>Металл Торг</span></span>
      </a>
      <div>Проспект Михаила Николаева, 1, Якутск Стройматериалы</div>
      <script>
        {"type":"website","value":"http://link.2gis.ru/1.2/demo?https://metalltorg.biz"}
      </script>
    </div>
    """

    seeds = parse_twogis_search_candidates(page_html, fallback_rubrics="стройматериалы")

    assert seeds == [
        CandidateDiscoverySeed(
            source_id="70000001007229923",
            display_name="Евролайн",
            address="Улица Курнатовского, 86",
            rubrics="Стройматериалы; доставка",
        ),
        CandidateDiscoverySeed(
            source_id="7037402698889811",
            display_name="Металл Торг",
            address="Проспект Михаила Николаева, 1",
            rubrics="Стройматериалы",
        ),
    ]


def test_parse_twogis_search_candidates_preserves_filter_signals() -> None:
    page_html = """
    <a href="/yakutsk/firm/70000001007229923" class="_1rehek">
      <span class="_lvwrwt"><span>Евролайн</span></span>
    </a>
    <div>Якутск Стройматериалы</div>
    """

    seeds = parse_twogis_search_candidates(
        page_html,
        fallback_rubrics="стройматериалы",
        has_prices_signal=True,
        has_website_signal=True,
    )

    assert seeds[0].has_prices_signal is True
    assert seeds[0].has_website_signal is True
    assert seeds[0].website_url is None


def test_parse_twogis_search_candidates_ignores_app_state_contacts_after_cards() -> None:
    page_html = (
        '<a href="/yakutsk/firm/7037402698916908" class="_1rehek">'
        '<span class="_lvwrwt"><span>Айта+М</span></span></a>'
        "<div>Якутск Стройматериалы</div>"
        + (" " * 8_500)
        + '{"contacts":[{"text":"pochta.ru","type":"website","value":"pochta.ru/offices/677007"}]}'
    )

    seeds = parse_twogis_search_candidates(page_html, fallback_rubrics="стройматериалы")

    assert seeds == [
        CandidateDiscoverySeed(
            source_id="7037402698916908",
            display_name="Айта+М",
            address="Якутск",
            rubrics="Стройматериалы",
        )
    ]


def test_extract_firm_website_ignores_servicing_contacts() -> None:
    page_html = """
    {"contacts":[
      {"url":"http://metalltorg.biz","type":"website",
       "value":"http://link.2gis.ru/1.2/demo?http://metalltorg.biz"}
    ],
    "servicing":{"items":[
      {"contacts":[{"type":"website","value":"pochta.ru/offices/677007"}]}
    ]}}
    """

    assert _extract_firm_website(page_html) == "http://metalltorg.biz"


def test_extract_firm_website_keeps_full_redirect_target_and_skips_messengers() -> None:
    page_html = """
    {"contacts":[
      {"type":"website",
       "value":"http://link.2gis.ru/1.2/demo?https://example.test/catalog/?utm_source=2gis"}
    ]}
    """
    messenger_html = """
    {"contacts":[
      {"type":"website","value":"http://link.2gis.ru/1.2/demo?http://max.ru/u/demo"}
    ]}
    """

    assert _extract_firm_website(page_html) == "https://example.test/catalog/?utm_source=2gis"
    assert _extract_firm_website(messenger_html) is None
