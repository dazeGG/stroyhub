from dataclasses import dataclass
from typing import Any

import httpx

JsonObject = dict[str, Any]

UNICOM_BASE_URL = "https://unicom-ykt.ru"
UNICOM_CATALOG_MENU_URL = f"{UNICOM_BASE_URL}/api/catalog-menu-2.php"
UNICOM_PRODUCTS_URL = f"{UNICOM_BASE_URL}/api2/v-catalog-beta/products"


class UnicomClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category_uuid: str | None = None,
        page: int | None = None,
        status_code: int | None = None,
    ) -> None:
        self.category_uuid = category_uuid
        self.page = page
        self.status_code = status_code

        details: list[str] = []
        if category_uuid is not None:
            details.append(f"category_uuid={category_uuid}")
        if page is not None:
            details.append(f"page={page}")
        if status_code is not None:
            details.append(f"status={status_code}")

        suffix = f" ({' '.join(details)})" if details else ""
        super().__init__(f"{message}{suffix}")


@dataclass(frozen=True, kw_only=True)
class UnicomCategory:
    id: str | None
    parent_id: str | None
    name: str
    name_en: str | None
    level: int | None
    is_leaf: bool
    uuid: str
    children: list["UnicomCategory"]
    raw: JsonObject


@dataclass(frozen=True, kw_only=True)
class UnicomProductPage:
    category_uuid: str
    page: int
    limit: int
    sort: str
    shop: str | None
    pages: int
    products_count: int | None
    products: list[JsonObject]
    stocks: list[JsonObject]
    filters: list[JsonObject]
    raw: JsonObject


@dataclass(frozen=True, kw_only=True)
class UnicomProductsResult:
    category_uuid: str
    limit: int
    sort: str
    shop: str | None
    pages: list[UnicomProductPage]
    products: list[JsonObject]
    products_count: int | None
    completeness: str
    stop_reason: str

    @property
    def is_complete(self) -> bool:
        return self.completeness == "complete"

    @property
    def is_partial(self) -> bool:
        return self.completeness == "partial"


class UnicomClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        catalog_menu_url: str = UNICOM_CATALOG_MENU_URL,
        products_url: str = UNICOM_PRODUCTS_URL,
        timeout: float = 20.0,
    ) -> None:
        self._client = client
        self._catalog_menu_url = catalog_menu_url
        self._products_url = products_url.rstrip("/")
        self._timeout = timeout

    def fetch_catalog_menu(self) -> list[UnicomCategory]:
        try:
            response = self._get(self._catalog_menu_url)
        except httpx.HTTPError as exc:
            raise UnicomClientError(f"Unicom catalog menu request failed: {exc}") from exc

        if response.status_code >= 400:
            raise UnicomClientError(
                "Unicom catalog menu returned an error",
                status_code=response.status_code,
            )

        payload = _json_payload(response, category_uuid=None, page=None)
        if not isinstance(payload, list):
            raise UnicomClientError(
                "Unicom catalog menu response is not a list",
                status_code=response.status_code,
            )

        return [_parse_category(item) for item in payload if isinstance(item, dict)]

    def fetch_leaf_category_uuids(self) -> tuple[str, ...]:
        return leaf_category_uuids(self.fetch_catalog_menu())

    def fetch_product_page(
        self,
        *,
        category_uuid: str,
        page: int = 1,
        limit: int = 50,
        sort: str = "popular",
        shop: str | None = "uc",
    ) -> UnicomProductPage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if limit < 1:
            raise ValueError("limit must be at least 1")

        params: dict[str, str | int] = {
            "page": page,
            "sort": sort,
            "limit": limit,
        }
        if shop is not None:
            params["shop"] = shop

        url = f"{self._products_url}/{category_uuid}"
        try:
            response = self._get(url, params=params)
        except httpx.HTTPError as exc:
            raise UnicomClientError(
                f"Unicom products request failed: {exc}",
                category_uuid=category_uuid,
                page=page,
            ) from exc

        if response.status_code >= 400:
            raise UnicomClientError(
                "Unicom products returned an error",
                category_uuid=category_uuid,
                page=page,
                status_code=response.status_code,
            )

        payload = _json_payload(response, category_uuid=category_uuid, page=page)
        if not isinstance(payload, dict):
            raise UnicomClientError(
                "Unicom products response is not an object",
                category_uuid=category_uuid,
                page=page,
                status_code=response.status_code,
            )

        return UnicomProductPage(
            category_uuid=category_uuid,
            page=page,
            limit=limit,
            sort=sort,
            shop=shop,
            pages=_positive_int(payload.get("pages")) or 1,
            products_count=_non_negative_int(payload.get("productsCount")),
            products=_list_of_objects(payload.get("products")),
            stocks=_list_of_objects(payload.get("stocks")),
            filters=_list_of_objects(payload.get("filters")),
            raw=payload,
        )

    def fetch_category_products(
        self,
        *,
        category_uuid: str,
        limit: int = 50,
        sort: str = "popular",
        shop: str | None = "uc",
        max_pages: int = 100,
    ) -> UnicomProductsResult:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        pages: list[UnicomProductPage] = []
        products: list[JsonObject] = []
        products_count: int | None = None
        expected_pages: int | None = None
        stop_reason = "empty_page"

        for page_number in range(1, max_pages + 1):
            page = self.fetch_product_page(
                category_uuid=category_uuid,
                page=page_number,
                limit=limit,
                sort=sort,
                shop=shop,
            )
            pages.append(page)
            products.extend(page.products)

            if products_count is None:
                products_count = page.products_count
            if expected_pages is None:
                expected_pages = page.pages

            if page_number >= page.pages:
                stop_reason = "source_pages_reached"
                break

            if not page.products:
                stop_reason = "empty_page"
                break
        else:
            stop_reason = "max_pages_reached"

        completeness = _completeness(
            pages=pages,
            stop_reason=stop_reason,
            products_seen=len(products),
            products_count=products_count,
            expected_pages=expected_pages,
        )

        return UnicomProductsResult(
            category_uuid=category_uuid,
            limit=limit,
            sort=sort,
            shop=shop,
            pages=pages,
            products=products,
            products_count=products_count,
            completeness=completeness,
            stop_reason=stop_reason,
        )

    def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, params=params)

        with httpx.Client(timeout=self._timeout) as client:
            return client.get(url, params=params)


def _json_payload(
    response: httpx.Response,
    *,
    category_uuid: str | None,
    page: int | None,
) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise UnicomClientError(
            "Unicom returned invalid JSON",
            category_uuid=category_uuid,
            page=page,
            status_code=response.status_code,
        ) from exc


def leaf_category_uuids(categories: list[UnicomCategory]) -> tuple[str, ...]:
    uuids: list[str] = []
    seen: set[str] = set()

    def walk(items: list[UnicomCategory]) -> None:
        for category in items:
            if category.is_leaf and category.uuid and category.uuid not in seen:
                seen.add(category.uuid)
                uuids.append(category.uuid)
            walk(category.children)

    walk(categories)
    return tuple(uuids)


def _parse_category(raw: JsonObject) -> UnicomCategory:
    children = [_parse_category(item) for item in _list_of_objects(raw.get("childs"))]
    return UnicomCategory(
        id=_string_or_none(raw.get("id")),
        parent_id=_string_or_none(raw.get("parent_id")),
        name=_string_or_empty(raw.get("name")),
        name_en=_string_or_none(raw.get("name_en")),
        level=_non_negative_int(raw.get("level")),
        is_leaf=raw.get("last") == "1",
        uuid=_string_or_empty(raw.get("uuid")),
        children=children,
        raw=raw,
    )


def _list_of_objects(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _positive_int(value: object) -> int | None:
    parsed = _int_or_none(value)
    if parsed is None or parsed < 1:
        return None
    return parsed


def _non_negative_int(value: object) -> int | None:
    parsed = _int_or_none(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _completeness(
    *,
    pages: list[UnicomProductPage],
    stop_reason: str,
    products_seen: int,
    products_count: int | None,
    expected_pages: int | None,
) -> str:
    if not pages:
        return "empty"

    if products_count == 0 or (products_count is None and products_seen == 0):
        return "empty"

    if stop_reason == "source_pages_reached":
        if products_count is None or products_seen >= products_count:
            return "complete"
        return "partial"

    if expected_pages is not None and len(pages) >= expected_pages:
        return "complete"

    return "partial"
