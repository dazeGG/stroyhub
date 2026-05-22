import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
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
CandidateDiscoverer = Callable[[], Iterable["CandidateDiscoverySeed"]]
TWOGIS_SEARCH_BASE_URL = "https://2gis.ru/yakutsk/search"
TWOGIS_DISCOVERY_QUERIES = (
    "стройматериалы",
    "строительные материалы",
    "пиломатериалы",
    "крепеж",
    "сантехника",
    "электрика",
)
TWOGIS_DISCOVERY_MAX_PAGES = 5


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
        seeds: Iterable[CandidateDiscoverySeed] | None = None,
        discoverer: CandidateDiscoverer | None = None,
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
        discovery = discoverer or discover_twogis_candidates
        discovery_seeds = seeds if seeds is not None else discovery()

        for seed in discovery_seeds:
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


def discover_twogis_candidates(
    *,
    queries: Iterable[str] = TWOGIS_DISCOVERY_QUERIES,
    max_pages: int = TWOGIS_DISCOVERY_MAX_PAGES,
    base_url: str = TWOGIS_SEARCH_BASE_URL,
) -> list[CandidateDiscoverySeed]:
    seeds_by_source_id: dict[str, CandidateDiscoverySeed] = {}
    with httpx.Client(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        for query in queries:
            for page in range(1, max_pages + 1):
                response = client.get(_search_page_url(base_url=base_url, query=query, page=page))
                response.raise_for_status()
                page_seeds = parse_twogis_search_candidates(
                    response.text,
                    fallback_rubrics=query,
                )
                if not page_seeds:
                    break
                for seed in page_seeds:
                    seeds_by_source_id.setdefault(seed.source_id, seed)

    return list(seeds_by_source_id.values())


def parse_twogis_search_candidates(
    page_html: str,
    *,
    fallback_rubrics: str,
) -> list[CandidateDiscoverySeed]:
    anchors = list(
        re.finditer(
            r'<a href="/yakutsk/firm/(?P<source_id>\d+)" class="_1rehek">'
            r'\s*<span class="_lvwrwt">\s*<span>(?P<name>.*?)</span>',
            page_html,
            flags=re.DOTALL,
        )
    )
    seeds_by_source_id: dict[str, CandidateDiscoverySeed] = {}

    for index, match in enumerate(anchors):
        source_id = match.group("source_id")
        if source_id in seeds_by_source_id:
            continue

        next_start = anchors[index + 1].start() if index + 1 < len(anchors) else len(page_html)
        # Search pages append a large JSON state after the visible cards. Keep the website
        # scan close to the card so nearby service contacts do not leak into candidates.
        next_start = min(next_start, match.start() + 8_000)
        card_html = page_html[match.start() : next_start]
        name = _html_text(match.group("name"))
        if not name:
            continue

        card_text = _html_text(card_html)
        seeds_by_source_id[source_id] = CandidateDiscoverySeed(
            source_id=source_id,
            display_name=name,
            address=_extract_address(card_text),
            rubrics=_extract_rubrics(card_text, fallback=fallback_rubrics),
            website_url=_extract_website(card_html),
        )

    return list(seeds_by_source_id.values())


def _search_page_url(*, base_url: str, query: str, page: int) -> str:
    url = f"{base_url.rstrip('/')}/{quote(query)}"
    if page > 1:
        url = f"{url}/page/{page}"
    return url


def _html_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def _extract_address(text: str) -> str:
    match = re.search(
        r"((?:Улица|Проспект|Переулок|Вилюйский тракт|Покровское шоссе|"
        r"Окружное шоссе|Сергеляхское шоссе)[^.;]{2,80}?,\s*\d[^.;]{0,40}?),\s*Якутск",
        text,
    )
    if match is None:
        return "Якутск"
    return match.group(1).strip()


def _extract_rubrics(text: str, *, fallback: str) -> str:
    if "Стройматериалы" in text and "Доставка" in text:
        return "Стройматериалы; доставка"
    if "Стройматериалы" in text:
        return "Стройматериалы"
    return fallback


def _extract_website(card_html: str) -> str | None:
    match = re.search(r'"type":"website","value":"(?P<value>[^"]+)"', card_html)
    if match is None:
        return None

    value = html.unescape(match.group("value"))
    if value.startswith("http://link.2gis.ru") and "?" in value:
        value = value.rsplit("?", maxsplit=1)[-1]
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if any(host in value for host in ("2gis.ru", "dgis.ru")):
        return None
    return value


def _priority(*, has_prices: bool, has_website: bool) -> tuple[int, str]:
    if has_prices and has_website:
        return 100, "есть цены и сайт"
    if has_prices:
        return 80, "есть цены"
    if has_website:
        return 60, "есть сайт"
    return 10, "нет цен и сайта"


def _approved_shop(session: Session, source_id: str) -> Shop | None:
    return session.scalar(
        select(Shop).where(Shop.source == TWOGIS_SOURCE, Shop.source_id == source_id)
    )


def _validate_status(status: str) -> None:
    if status not in SHOP_CANDIDATE_STATUSES:
        raise ValueError(f"unknown shop source candidate status: {status}")
