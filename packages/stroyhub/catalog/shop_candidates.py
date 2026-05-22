import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from stroyhub.db.repositories import (
    ShopRepository,
    ShopUpsert,
)
from stroyhub.models import Shop, ShopIdentity, ShopSourceCandidate

TWOGIS_SOURCE = "2gis"
CandidateDiscoverer = Callable[[], Iterable["CandidateDiscoverySeed"]]
TWOGIS_SEARCH_BASE_URL = "https://2gis.ru/yakutsk/search"
TWOGIS_DISCOVERY_QUERY = "стройматериалы"
TWOGIS_DISCOVERY_MAX_PAGES = 50
OFFICIAL_STRATEGY_PRIORITY_BONUS = 1_000


@dataclass(frozen=True, kw_only=True)
class OfficialSourceStrategy:
    source: str
    source_type: str
    label: str
    match_names: tuple[str, ...]
    twogis_source_ids: tuple[str, ...] = ()


IMPLEMENTED_OFFICIAL_STRATEGIES = (
    OfficialSourceStrategy(
        source="unicom",
        source_type="official_api",
        label="Юником API",
        match_names=("юником",),
        twogis_source_ids=(
            "7037402698746785",
            "70000001058951900",
            "70000001019786573",
        ),
    ),
    OfficialSourceStrategy(
        source="metalltorg",
        source_type="official_html",
        label="Металл Торг HTML",
        match_names=("металл торг", "металлторг"),
        twogis_source_ids=(
            "7037402698889811",
            "7037402698767155",
            "70000001033120495",
        ),
    ),
)


@dataclass(frozen=True, kw_only=True)
class CandidateDiscoverySeed:
    source_id: str
    display_name: str
    address: str
    rubrics: str
    website_url: str | None = None
    has_prices_signal: bool = False
    has_website_signal: bool = False


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


@dataclass(frozen=True, kw_only=True)
class CandidateIdentitySuggestion:
    id: int
    display_name: str
    status: str
    source_count: int
    reason: str


SHOP_CANDIDATE_STATUSES = frozenset({"pending", "stale", "hidden", "archived", "approved"})


class ShopCandidateCatalog:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._identity_suggestion_sources: list[ShopIdentity] | None = None

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
        refreshed_at: datetime | None = None,
    ) -> CandidateRefreshSummary:
        now = refreshed_at or datetime.now(UTC)
        checked = 0
        created = 0
        updated = 0
        skipped_approved = 0
        seen_source_ids: set[str] = set()
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
            priority, reason = _priority(
                has_prices=seed.has_prices_signal,
                has_website=seed.has_website_signal,
            )
            official_strategy = _official_strategy_for_seed(seed)
            if official_strategy is not None:
                priority += OFFICIAL_STRATEGY_PRIORITY_BONUS

            candidate.display_name = seed.display_name
            candidate.address = seed.address
            candidate.website_url = seed.website_url
            candidate.rubrics = seed.rubrics
            if candidate.status not in {"hidden", "archived"}:
                candidate.status = "pending"
            candidate.has_products = seed.has_prices_signal
            candidate.has_prices = seed.has_prices_signal
            candidate.has_website = seed.has_website_signal
            candidate.product_count = 0
            candidate.priced_product_count = 0
            candidate.priority = priority
            candidate.priority_reason = reason
            candidate.last_seen_at = now
            candidate.last_checked_at = now
            candidate.missing_since = None
            candidate.raw = {
                "source": TWOGIS_SOURCE,
                "source_id": seed.source_id,
                "rubrics": seed.rubrics,
                "signals": {
                    "has_prices": seed.has_prices_signal,
                    "has_website": seed.has_website_signal,
                },
            }
            if official_strategy is not None:
                candidate.raw["official_strategy"] = {
                    "source": official_strategy.source,
                    "source_type": official_strategy.source_type,
                    "label": official_strategy.label,
                    "status": "implemented",
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

    def suggest_identity(
        self,
        candidate: ShopSourceCandidate,
    ) -> CandidateIdentitySuggestion | None:
        candidate_key = _normalize_identity_key(candidate.display_name)
        if not candidate_key:
            return None

        for identity in self._identity_sources_for_suggestions():
            identity_keys = [_normalize_identity_key(identity.display_name)]
            identity_keys.extend(
                _normalize_identity_key(shop.name) for shop in identity.source_shops
            )
            if any(_strong_identity_match(candidate_key, key) for key in identity_keys):
                return CandidateIdentitySuggestion(
                    id=identity.id,
                    display_name=identity.display_name,
                    status=identity.status,
                    source_count=len(identity.source_shops),
                    reason="name_match",
                )

        return None

    def _identity_sources_for_suggestions(self) -> list[ShopIdentity]:
        if self._identity_suggestion_sources is None:
            self._identity_suggestion_sources = list(
                self._session.scalars(
                    select(ShopIdentity).order_by(
                        ShopIdentity.display_name.asc(),
                        ShopIdentity.id.asc(),
                    )
                )
            )
        return self._identity_suggestion_sources

    def approve(
        self,
        candidate_id: int,
        *,
        shop_identity_id: int | None = None,
    ) -> ShopSourceCandidate:
        candidate = self._session.get(ShopSourceCandidate, candidate_id)
        if candidate is None:
            raise ValueError("shop source candidate not found")
        if candidate.status == "approved" and candidate.approved_shop_id is not None:
            return candidate
        if candidate.status in {"hidden", "archived"}:
            raise ValueError("hidden or archived candidate cannot be approved")

        website_url = candidate.website_url
        if website_url is None and candidate.has_website:
            website_url = _resolve_candidate_website(candidate.source_id)
            candidate.website_url = website_url

        shop = ShopRepository(self._session).upsert(
            ShopUpsert(
                source=TWOGIS_SOURCE,
                source_id=candidate.source_id,
                source_type="2gis",
                name=candidate.display_name,
                shop_identity_id=shop_identity_id,
                address=candidate.address,
                url=website_url,
                scrape_status="scheduled",
                raw={
                    "source": TWOGIS_SOURCE,
                    "source_id": candidate.source_id,
                    "candidate_id": candidate.id,
                    "rubrics": candidate.rubrics,
                    "signals": {
                        "has_prices": candidate.has_prices,
                        "has_website": candidate.has_website,
                    },
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


def discover_twogis_candidates(
    *,
    query: str = TWOGIS_DISCOVERY_QUERY,
    max_pages: int = TWOGIS_DISCOVERY_MAX_PAGES,
    base_url: str = TWOGIS_SEARCH_BASE_URL,
) -> list[CandidateDiscoverySeed]:
    seeds_by_source_id: dict[str, CandidateDiscoverySeed] = {}
    discovery_layers = (
        ("has_site%2Csorting_has_goods", True, True),
        ("sorting_has_goods", True, False),
        ("has_site", False, True),
        (None, False, False),
    )
    with httpx.Client(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        for filters, has_prices_signal, has_website_signal in discovery_layers:
            for seed in _discover_twogis_filtered_candidates(
                client=client,
                query=query,
                max_pages=max_pages,
                base_url=base_url,
                filters=filters,
                has_prices_signal=has_prices_signal,
                has_website_signal=has_website_signal,
            ):
                existing = seeds_by_source_id.get(seed.source_id)
                seeds_by_source_id[seed.source_id] = (
                    seed if existing is None else _merge_seed(existing, seed)
                )

    return list(seeds_by_source_id.values())


def _discover_twogis_filtered_candidates(
    *,
    client: httpx.Client,
    query: str,
    max_pages: int,
    base_url: str,
    filters: str | None,
    has_prices_signal: bool,
    has_website_signal: bool,
) -> list[CandidateDiscoverySeed]:
    seeds_by_source_id: dict[str, CandidateDiscoverySeed] = {}

    for page in range(1, max_pages + 1):
        response = client.get(
            _search_page_url(base_url=base_url, query=query, page=page, filters=filters)
        )
        response.raise_for_status()
        page_seeds = parse_twogis_search_candidates(
            response.text,
            fallback_rubrics=query,
            has_prices_signal=has_prices_signal,
            has_website_signal=has_website_signal,
        )
        if not page_seeds:
            break

        has_new_seed = False
        for seed in page_seeds:
            existing = seeds_by_source_id.get(seed.source_id)
            if existing is None:
                has_new_seed = True
            seeds_by_source_id[seed.source_id] = (
                seed if existing is None else _merge_seed(existing, seed)
            )
        if not has_new_seed:
            break

    return list(seeds_by_source_id.values())


def parse_twogis_search_candidates(
    page_html: str,
    *,
    fallback_rubrics: str,
    has_prices_signal: bool = False,
    has_website_signal: bool = False,
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
            has_prices_signal=has_prices_signal,
            has_website_signal=has_website_signal,
        )

    return list(seeds_by_source_id.values())


def _search_page_url(
    *,
    base_url: str,
    query: str,
    page: int,
    filters: str | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/{quote(query)}"
    if filters is not None:
        url = f"{url}/filters/{filters}"
    if page > 1:
        url = f"{url}/page/{page}"
    return url


def _fetch_twogis_firm_website(client: httpx.Client, source_id: str) -> str | None:
    response = client.get(f"https://2gis.ru/yakutsk/firm/{source_id}")
    response.raise_for_status()
    return _extract_firm_website(response.text)


def _resolve_candidate_website(source_id: str) -> str | None:
    try:
        with httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:
            return _fetch_twogis_firm_website(client, source_id)
    except httpx.HTTPError:
        return None


def _merge_seed(
    existing: CandidateDiscoverySeed,
    incoming: CandidateDiscoverySeed,
) -> CandidateDiscoverySeed:
    return CandidateDiscoverySeed(
        source_id=existing.source_id,
        display_name=existing.display_name or incoming.display_name,
        address=existing.address or incoming.address,
        rubrics=existing.rubrics or incoming.rubrics,
        website_url=existing.website_url or incoming.website_url,
        has_prices_signal=existing.has_prices_signal or incoming.has_prices_signal,
        has_website_signal=existing.has_website_signal or incoming.has_website_signal,
    )


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
    match = re.search(r'\{[^{}]*"type":"website"[^{}]*"value":"(?P<value>[^"]+)"', card_html)
    if match is None:
        match = re.search(r'\{[^{}]*"value":"(?P<value>[^"]+)"[^{}]*"type":"website"', card_html)
    if match is None:
        return None

    value = html.unescape(match.group("value"))
    if value.startswith("http://link.2gis.ru") and "?" in value:
        value = value.split("?", maxsplit=1)[-1]
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    hostname = urlparse(value).hostname or ""
    if (
        not hostname
        or any(host in hostname for host in ("2gis.ru", "dgis.ru"))
        or hostname == "max.ru"
    ):
        return None
    return value


def _extract_firm_website(page_html: str) -> str | None:
    own_firm_html = page_html.split('"servicing"', maxsplit=1)[0]
    return _extract_website(own_firm_html)


def _priority(*, has_prices: bool, has_website: bool) -> tuple[int, str]:
    if has_prices and has_website:
        return 100, "есть цены и сайт"
    if has_prices:
        return 80, "есть цены"
    if has_website:
        return 60, "есть сайт"
    return 10, "нет цен и сайта"


def _official_strategy_for_seed(seed: CandidateDiscoverySeed) -> OfficialSourceStrategy | None:
    normalized_name = _normalize_match_text(seed.display_name)
    for strategy in IMPLEMENTED_OFFICIAL_STRATEGIES:
        if seed.source_id in strategy.twogis_source_ids:
            return strategy
        if any(name in normalized_name for name in strategy.match_names):
            return strategy

    return None


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def _normalize_identity_key(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.casefold().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", normalized)


def _strong_identity_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= 5 and (left in right or right in left)


def _approved_shop(session: Session, source_id: str) -> Shop | None:
    return session.scalar(
        select(Shop).where(Shop.source == TWOGIS_SOURCE, Shop.source_id == source_id)
    )


def _validate_status(status: str) -> None:
    if status not in SHOP_CANDIDATE_STATUSES:
        raise ValueError(f"unknown shop source candidate status: {status}")
