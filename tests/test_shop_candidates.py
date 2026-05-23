from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.catalog.shop_candidates import (
    CandidateDiscoverySeed,
    CandidateListFilters,
    ShopCandidateCatalog,
    _discover_twogis_filtered_candidates,
    _extract_firm_website,
    _search_page_url,
    parse_twogis_search_candidates,
)
from stroyhub.core.config import settings
from stroyhub.db import ShopIdentityCreate, ShopIdentityRepository, ShopRepository, ShopUpsert
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


def test_candidate_verification_confirms_site_and_products(db_session: Session) -> None:
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="verify-both",
                display_name="Verify Both",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
        refreshed_at=datetime(2026, 5, 23, 1, 0, tzinfo=UTC),
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]

    verified, summary = catalog.verify_twogis_data(
        candidate.id,
        website_resolver=lambda source_id: "https://verify.example.test/",
        product_probe=lambda source_id: SimpleNamespace(
            total=12,
            items_seen=1,
            products=[SimpleNamespace(price=Decimal("100.00"))],
            completeness="partial",
            stop_reason="max_pages_reached",
        ),
        checked_at=datetime(2026, 5, 23, 2, 0, tzinfo=UTC),
    )

    assert summary.website_found is True
    assert summary.products_found is True
    assert verified.has_website is True
    assert verified.has_prices is True
    assert verified.has_products is True
    assert verified.website_url == "https://verify.example.test/"
    assert verified.product_count == 12
    assert verified.priced_product_count == 1
    assert verified.priority == 100
    assert verified.priority_reason == "есть цены и сайт"
    assert verified.raw["verification"]["website_found"] is True
    assert verified.raw["verification"]["products_found"] is True


def test_candidate_verification_drops_unconfirmed_signals(db_session: Session) -> None:
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="verify-none",
                display_name="Verify None",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
        refreshed_at=datetime(2026, 5, 23, 1, 0, tzinfo=UTC),
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]

    verified, summary = catalog.verify_twogis_data(
        candidate.id,
        website_resolver=lambda source_id: None,
        product_probe=lambda source_id: SimpleNamespace(
            total=0,
            items_seen=0,
            products=[],
            completeness="empty",
            stop_reason="source_total_reached",
        ),
        checked_at=datetime(2026, 5, 23, 2, 0, tzinfo=UTC),
    )

    assert summary.website_found is False
    assert summary.products_found is False
    assert verified.has_website is False
    assert verified.has_prices is False
    assert verified.has_products is False
    assert verified.website_url is None
    assert verified.product_count == 0
    assert verified.priced_product_count == 0
    assert verified.priority == 10
    assert verified.priority_reason == "нет цен и сайта"


def test_candidate_refresh_prioritizes_implemented_official_strategy(
    db_session: Session,
) -> None:
    catalog = ShopCandidateCatalog(db_session)

    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="ordinary",
                display_name="Ordinary Prices Website",
                address="Yakutsk",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            ),
            CandidateDiscoverySeed(
                source_id="7037402698746785",
                display_name="Юником",
                address="Вилюйский тракт 3 километр, 1/4",
                rubrics="Стройматериалы",
                has_website_signal=True,
            ),
        ],
    )

    items = catalog.list_candidates(CandidateListFilters())

    assert [item.source_id for item in items] == ["7037402698746785", "ordinary"]
    assert items[0].priority == 1060
    assert items[0].raw["official_strategy"] == {
        "source": "unicom",
        "source_type": "official_api",
        "label": "Юником API",
        "status": "implemented",
    }


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
    assert shop.address == "Yakutsk"
    assert shop.url == "https://approve-me.example.test/"
    assert shop.shop_identity_id is None
    assert shop.shop_identity is None


def test_candidate_approval_uses_verified_website_without_resolving_again(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="verified-approve",
                display_name="Verified Approve",
                address="Yakutsk, Verified 1",
                rubrics="Стройматериалы",
                has_prices_signal=True,
                has_website_signal=True,
            )
        ],
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]
    catalog.verify_twogis_data(
        candidate.id,
        website_resolver=lambda source_id: "https://verified.example.test/",
        product_probe=lambda source_id: SimpleNamespace(
            total=0,
            items_seen=0,
            products=[],
            completeness="empty",
            stop_reason="source_total_reached",
        ),
    )
    monkeypatch.setattr(
        "stroyhub.catalog.shop_candidates._resolve_candidate_website",
        lambda source_id: pytest.fail("verified website should already be stored"),
    )

    catalog.approve(candidate.id)
    shop = db_session.scalar(select(Shop).where(Shop.source_id == "verified-approve"))

    assert shop is not None
    assert shop.address == "Yakutsk, Verified 1"
    assert shop.url == "https://verified.example.test/"


def test_candidate_suggests_existing_identity_by_name(db_session: Session) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Металл Торг", address="Якутск")
    )
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="metalltorg-branch",
                display_name="Металлторг",
                address="Проспект Михаила Николаева, 1",
                rubrics="Стройматериалы",
                has_prices_signal=True,
            )
        ],
    )

    candidate = catalog.list_candidates(CandidateListFilters())[0]
    suggestion = catalog.suggest_identity(candidate)

    assert suggestion is not None
    assert suggestion.id == identity.id
    assert suggestion.display_name == "Металл Торг"
    assert suggestion.reason == "name_match"


def test_candidate_approval_can_link_to_existing_identity(db_session: Session) -> None:
    identity = ShopIdentityRepository(db_session).create(
        ShopIdentityCreate(display_name="Юником", address="Якутск")
    )
    catalog = ShopCandidateCatalog(db_session)
    catalog.refresh_from_twogis(
        seeds=[
            CandidateDiscoverySeed(
                source_id="unicom-branch",
                display_name="Юником",
                address="Вилюйский тракт 3 километр, 1/4",
                rubrics="Стройматериалы",
                has_prices_signal=True,
            )
        ],
    )
    candidate = catalog.list_candidates(CandidateListFilters())[0]

    catalog.approve(candidate.id, shop_identity_id=identity.id)
    shop = db_session.scalar(select(Shop).where(Shop.source_id == "unicom-branch"))

    assert shop is not None
    assert shop.shop_identity_id == identity.id
    assert shop.address == "Вилюйский тракт 3 километр, 1/4"


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


def test_search_page_url_uses_single_discovery_query_with_filters() -> None:
    url = _search_page_url(
        base_url="https://2gis.ru/yakutsk/search",
        query="стройматериалы",
        page=3,
        filters="has_site%2Csorting_has_goods",
    )

    assert url == (
        "https://2gis.ru/yakutsk/search/"
        "%D1%81%D1%82%D1%80%D0%BE%D0%B9%D0%BC%D0%B0%D1%82%D0%B5%D1%80%D0%B8%D0%B0%D0%BB%D1%8B"
        "/filters/has_site%2Csorting_has_goods/page/3"
    )


def test_filtered_discovery_stops_when_page_repeats_without_new_sources() -> None:
    page_one = """
    <a href="/yakutsk/firm/1" class="_1rehek"><span class="_lvwrwt"><span>Первый</span></span></a>
    <div>Якутск Стройматериалы</div>
    """
    page_two = """
    <a href="/yakutsk/firm/2" class="_1rehek"><span class="_lvwrwt"><span>Второй</span></span></a>
    <div>Якутск Стройматериалы</div>
    """
    client = _FakeSearchClient([page_one, page_two, page_two])

    seeds = _discover_twogis_filtered_candidates(
        client=client,
        query="стройматериалы",
        max_pages=50,
        base_url="https://2gis.ru/yakutsk/search",
        filters="sorting_has_goods",
        has_prices_signal=True,
        has_website_signal=False,
    )

    assert [seed.source_id for seed in seeds] == ["1", "2"]
    assert client.request_count == 3


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


class _FakeSearchResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _FakeSearchClient:
    def __init__(self, pages: list[str]) -> None:
        self._pages = pages
        self.request_count = 0

    def get(self, url: str) -> _FakeSearchResponse:
        self.request_count += 1
        index = min(self.request_count - 1, len(self._pages) - 1)
        return _FakeSearchResponse(self._pages[index])
