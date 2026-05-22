from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopRepository,
    ShopUpsert,
)
from stroyhub.models import Shop, ShopSourceCandidate
from stroyhub.scraping import TwogisScrapeResult, scrape_twogis_branch

TWOGIS_SOURCE = "2gis"
CandidateScraper = Callable[[str], TwogisScrapeResult]


@dataclass(frozen=True, kw_only=True)
class CandidateDiscoverySeed:
    source_id: str
    display_name: str
    address: str
    rubrics: str
    website_url: str | None = None


@dataclass(frozen=True, kw_only=True)
class CandidateListFilters:
    status: str | None = None
    include_approved: bool = False


@dataclass(frozen=True, kw_only=True)
class CandidateRefreshSummary:
    checked: int
    created: int
    updated: int
    stale: int
    skipped_approved: int


SHOP_CANDIDATE_STATUSES = frozenset({"pending", "stale", "hidden", "archived", "approved"})

DEFAULT_DISCOVERY_SEEDS = (
    CandidateDiscoverySeed(
        source_id="7037402698889811",
        display_name="Металл Торг",
        address="Проспект Михаила Николаева, 1",
        rubrics="Стройматериалы; доставка",
        website_url="https://metalltorg.biz/catalog/",
    ),
    CandidateDiscoverySeed(
        source_id="70000001007229923",
        display_name="Евролайн",
        address="Улица Курнатовского, 86",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateDiscoverySeed(
        source_id="7037402698746785",
        display_name="Юником",
        address="Вилюйский тракт 3 километр, 1/4",
        rubrics="Стройматериалы; доставка",
        website_url="https://unicom-ykt.ru/",
    ),
    CandidateDiscoverySeed(
        source_id="7037402698836780",
        display_name="Пирамида",
        address="Переулок Космачёва, 2",
        rubrics="Стройматериалы",
    ),
    CandidateDiscoverySeed(
        source_id="7037402698755240",
        display_name="Космос",
        address="Улица Космонавтов, 23",
        rubrics="Стройматериалы; доставка",
        website_url="https://kosmos-ykt.ru/catalog",
    ),
    CandidateDiscoverySeed(
        source_id="70000001038286835",
        display_name="ЛидерСтрой",
        address="Улица Жорницкого, 50а",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateDiscoverySeed(
        source_id="70000001065271367",
        display_name="СибНорд",
        address="Улица Челюскина, 37/7в",
        rubrics="Стройматериалы; доставка",
        website_url="https://sibnord.ru/",
    ),
    CandidateDiscoverySeed(
        source_id="7037402698774152",
        display_name="Ондулин",
        address="Улица Чернышевского, 48",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateDiscoverySeed(
        source_id="7037402698745664",
        display_name="Интехстрой",
        address="Улица Леваневского, 3",
        rubrics="Стройматериалы; доставка",
        website_url="https://its96.ru/",
    ),
    CandidateDiscoverySeed(
        source_id="70000001062470950",
        display_name="Востоктехторг",
        address="Проспект Михаила Николаева, 25/5",
        rubrics="Стройматериалы; доставка",
        website_url="https://vtt14.ru/catalog/",
    ),
    CandidateDiscoverySeed(
        source_id="70000001021201334",
        display_name="Строительный мир",
        address="Улица Чернышевского, 105",
        rubrics="Стройматериалы; доставка",
        website_url="https://orion-expressiya.ru/",
    ),
)


class ShopCandidateCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_candidates(self, filters: CandidateListFilters) -> list[ShopSourceCandidate]:
        statement = select(ShopSourceCandidate)
        if filters.status is not None:
            status = filters.status.strip()
            if status:
                _validate_status(status)
                statement = statement.where(ShopSourceCandidate.status == status)
        elif not filters.include_approved:
            statement = statement.where(ShopSourceCandidate.status != "approved")

        statement = statement.order_by(
            ShopSourceCandidate.priority.desc(),
            ShopSourceCandidate.display_name.asc(),
            ShopSourceCandidate.id.asc(),
        )
        return list(self._session.scalars(statement))

    def refresh_from_twogis(
        self,
        *,
        seeds: Iterable[CandidateDiscoverySeed] = DEFAULT_DISCOVERY_SEEDS,
        scraper: CandidateScraper | None = None,
        refreshed_at: datetime | None = None,
    ) -> CandidateRefreshSummary:
        now = refreshed_at or datetime.now(UTC)
        checked = 0
        created = 0
        updated = 0
        skipped_approved = 0
        seen_source_ids: set[str] = set()
        scrape = scraper or _default_scraper

        for seed in seeds:
            checked += 1
            seen_source_ids.add(seed.source_id)
            approved_shop = _approved_shop(self._session, seed.source_id)
            if approved_shop is not None:
                skipped_approved += 1
                candidate = self._get_by_source_id(seed.source_id)
                if candidate is not None and candidate.status != "approved":
                    candidate.status = "approved"
                    candidate.approved_shop_id = approved_shop.id
                continue

            candidate = self._get_or_create(seed)
            was_new = candidate.id is None
            signal = _candidate_signal(seed, scrape)
            priority, reason = _priority(
                has_prices=signal.priced_product_count > 0,
                has_website=seed.website_url is not None,
            )

            candidate.display_name = seed.display_name
            candidate.address = seed.address
            candidate.website_url = seed.website_url
            candidate.rubrics = seed.rubrics
            if candidate.status not in {"hidden", "archived"}:
                candidate.status = "pending"
            candidate.has_products = signal.product_count > 0
            candidate.has_prices = signal.priced_product_count > 0
            candidate.has_website = seed.website_url is not None
            candidate.product_count = signal.product_count
            candidate.priced_product_count = signal.priced_product_count
            candidate.priority = priority
            candidate.priority_reason = reason
            candidate.last_seen_at = now
            candidate.last_checked_at = now
            candidate.missing_since = None
            candidate.raw = {
                "source": TWOGIS_SOURCE,
                "source_id": seed.source_id,
                "rubrics": seed.rubrics,
                "total": signal.total,
                "completeness": signal.completeness,
                "stop_reason": signal.stop_reason,
                "error": signal.error,
            }
            self._session.flush()
            if was_new:
                created += 1
            else:
                updated += 1

        stale = self._mark_missing_candidates_stale(seen_source_ids, now)
        self._session.flush()
        return CandidateRefreshSummary(
            checked=checked,
            created=created,
            updated=updated,
            stale=stale,
            skipped_approved=skipped_approved,
        )

    def approve(self, candidate_id: int) -> ShopSourceCandidate:
        candidate = self._session.get(ShopSourceCandidate, candidate_id)
        if candidate is None:
            raise ValueError("shop source candidate not found")
        if candidate.status == "approved" and candidate.approved_shop_id is not None:
            return candidate
        if candidate.status in {"hidden", "archived"}:
            raise ValueError("hidden or archived candidate cannot be approved")

        identity = ShopIdentityRepository(self._session).create(
            ShopIdentityCreate(
                display_name=candidate.display_name,
                address=candidate.address,
                website_url=candidate.website_url,
                preferred_source=TWOGIS_SOURCE,
            )
        )
        shop = ShopRepository(self._session).upsert(
            ShopUpsert(
                source=TWOGIS_SOURCE,
                source_id=candidate.source_id,
                source_type="2gis",
                shop_identity_id=identity.id,
                name=candidate.display_name,
                address=candidate.address,
                url=candidate.website_url,
                scrape_status="scheduled",
                raw={
                    "source": TWOGIS_SOURCE,
                    "source_id": candidate.source_id,
                    "candidate_id": candidate.id,
                    "rubrics": candidate.rubrics,
                },
            )
        )
        candidate.status = "approved"
        candidate.approved_shop_id = shop.id
        self._session.flush()
        return candidate

    def _get_by_source_id(self, source_id: str) -> ShopSourceCandidate | None:
        return self._session.scalar(
            select(ShopSourceCandidate).where(
                ShopSourceCandidate.source == TWOGIS_SOURCE,
                ShopSourceCandidate.source_id == source_id,
            )
        )

    def _get_or_create(self, seed: CandidateDiscoverySeed) -> ShopSourceCandidate:
        candidate = self._get_by_source_id(seed.source_id)
        if candidate is not None:
            return candidate

        candidate = ShopSourceCandidate(
            source=TWOGIS_SOURCE,
            source_id=seed.source_id,
            source_type="2gis",
            display_name=seed.display_name,
            priority_reason="not checked yet",
        )
        self._session.add(candidate)
        return candidate

    def _mark_missing_candidates_stale(
        self,
        seen_source_ids: set[str],
        missing_since: datetime,
    ) -> int:
        candidates = self._session.scalars(
            select(ShopSourceCandidate).where(
                ShopSourceCandidate.source == TWOGIS_SOURCE,
                ShopSourceCandidate.status == "pending",
            )
        )
        count = 0
        for candidate in candidates:
            if candidate.source_id in seen_source_ids:
                continue
            candidate.status = "stale"
            if candidate.missing_since is None:
                candidate.missing_since = missing_since
            count += 1
        return count


@dataclass(frozen=True, kw_only=True)
class _CandidateSignal:
    product_count: int
    priced_product_count: int
    total: int | None
    completeness: str | None
    stop_reason: str | None
    error: str | None = None


def _candidate_signal(
    seed: CandidateDiscoverySeed,
    scrape: CandidateScraper,
) -> _CandidateSignal:
    try:
        result = scrape(seed.source_id)
    except Exception as exc:
        return _CandidateSignal(
            product_count=0,
            priced_product_count=0,
            total=None,
            completeness="failed",
            stop_reason=type(exc).__name__,
            error=str(exc),
        )

    return _CandidateSignal(
        product_count=len(result.products),
        priced_product_count=sum(1 for product in result.products if product.price is not None),
        total=result.total,
        completeness=result.completeness,
        stop_reason=result.stop_reason,
    )


def _default_scraper(source_id: str) -> TwogisScrapeResult:
    return scrape_twogis_branch(branch_id=source_id, page_size=50, max_pages=3)


def _priority(*, has_prices: bool, has_website: bool) -> tuple[int, str]:
    if has_prices and has_website:
        return 100, "есть цены и сайт"
    if has_prices:
        return 80, "есть цены"
    if has_website:
        return 60, "есть сайт, цен не найдено"
    return 10, "цен не найдено"


def _approved_shop(session: Session, source_id: str) -> Shop | None:
    return session.scalar(
        select(Shop).where(Shop.source == TWOGIS_SOURCE, Shop.source_id == source_id)
    )


def _validate_status(status: str) -> None:
    if status not in SHOP_CANDIDATE_STATUSES:
        raise ValueError(f"unknown shop source candidate status: {status}")
