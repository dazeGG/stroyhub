from dataclasses import dataclass
from typing import Any

import httpx

JsonObject = dict[str, Any]

ITEMS_BY_BRANCH_URL = "https://market-backend.api.2gis.ru/5.0/product/items_by_branch"


class TwogisClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        branch_id: str,
        page: int,
        status_code: int | None = None,
    ) -> None:
        self.branch_id = branch_id
        self.page = page
        self.status_code = status_code
        details = f"branch_id={branch_id} page={page}"
        if status_code is not None:
            details = f"{details} status={status_code}"
        super().__init__(f"{message} ({details})")


@dataclass(frozen=True, kw_only=True)
class TwogisBranchPage:
    branch_id: str
    page: int
    page_size: int
    total: int | None
    updated_at_raw: str | None
    items: list[JsonObject]
    pinned_items: list[JsonObject]
    raw: JsonObject


@dataclass(frozen=True, kw_only=True)
class TwogisBranchItems:
    branch_id: str
    page_size: int
    pages: list[TwogisBranchPage]
    items: list[JsonObject]
    pinned_items: list[JsonObject]
    total: int | None
    completeness: str
    stop_reason: str

    @property
    def is_complete(self) -> bool:
        return self.completeness == "complete"

    @property
    def is_partial(self) -> bool:
        return self.completeness == "partial"


class TwogisClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = ITEMS_BY_BRANCH_URL,
        timeout: float = 20.0,
    ) -> None:
        self._client = client
        self._base_url = base_url
        self._timeout = timeout

    def fetch_branch_page(
        self,
        *,
        branch_id: str,
        page: int = 1,
        page_size: int = 50,
        locale: str = "ru_RU",
    ) -> TwogisBranchPage:
        params: dict[str, str | int] = {
            "branch_id": branch_id,
            "locale": locale,
            "page": page,
            "page_size": page_size,
        }

        try:
            response = self._request(params)
        except httpx.HTTPError as exc:
            raise TwogisClientError(
                f"2GIS request failed: {exc}",
                branch_id=branch_id,
                page=page,
            ) from exc

        if response.status_code >= 400:
            raise TwogisClientError(
                "2GIS returned an error",
                branch_id=branch_id,
                page=page,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TwogisClientError(
                "2GIS returned invalid JSON",
                branch_id=branch_id,
                page=page,
                status_code=response.status_code,
            ) from exc

        meta_code = _meta_code(payload)
        if meta_code is not None and meta_code >= 400:
            raise TwogisClientError(
                "2GIS returned an API error",
                branch_id=branch_id,
                page=page,
                status_code=meta_code,
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise TwogisClientError(
                "2GIS response does not contain result object",
                branch_id=branch_id,
                page=page,
                status_code=response.status_code,
            )

        items = _list_of_objects(result.get("items"))
        pinned_items = _list_of_objects(result.get("pinned_items"))
        total = result.get("total")

        updated_at = result.get("updated_at")

        return TwogisBranchPage(
            branch_id=branch_id,
            page=page,
            page_size=page_size,
            total=total if isinstance(total, int) else None,
            updated_at_raw=updated_at if isinstance(updated_at, str) else None,
            items=items,
            pinned_items=pinned_items,
            raw=payload,
        )

    def fetch_branch_items(
        self,
        *,
        branch_id: str,
        page_size: int = 50,
        locale: str = "ru_RU",
        max_pages: int = 100,
    ) -> TwogisBranchItems:
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        return self.fetch_branch_items_window(
            branch_id=branch_id,
            start_page=1,
            page_size=page_size,
            locale=locale,
            max_pages=max_pages,
            limit_stop_reason="max_pages_reached",
        )

    def fetch_branch_items_window(
        self,
        *,
        branch_id: str,
        start_page: int,
        page_size: int = 50,
        locale: str = "ru_RU",
        max_pages: int = 100,
        limit_stop_reason: str = "window_limit_reached",
    ) -> TwogisBranchItems:
        if start_page < 1:
            raise ValueError("start_page must be at least 1")
        if page_size < 1:
            raise ValueError("page_size must be at least 1")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        pages: list[TwogisBranchPage] = []
        items: list[JsonObject] = []
        pinned_items_by_product_id: dict[str, JsonObject] = {}
        total: int | None = None
        stop_reason = "empty_page"

        for page_number in range(start_page, start_page + max_pages):
            page = self.fetch_branch_page(
                branch_id=branch_id,
                page=page_number,
                page_size=page_size,
                locale=locale,
            )
            pages.append(page)

            if total is None and page.total is not None:
                total = page.total

            items.extend(page.items)
            _merge_pinned_items(pinned_items_by_product_id, page.pinned_items)

            fetched_until = (start_page - 1) * page_size + len(items)
            if total is not None and fetched_until >= total:
                stop_reason = "source_total_reached"
                break

            if not page.items:
                stop_reason = "empty_page"
                break
        else:
            stop_reason = limit_stop_reason

        completeness = _completeness(
            pages=pages,
            item_count=len(items),
            total=total,
            stop_reason=stop_reason,
        )

        return TwogisBranchItems(
            branch_id=branch_id,
            page_size=page_size,
            pages=pages,
            items=items,
            pinned_items=list(pinned_items_by_product_id.values()),
            total=total,
            completeness=completeness,
            stop_reason=stop_reason,
        )

    def _request(self, params: dict[str, str | int]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(self._base_url, params=params)

        with httpx.Client(timeout=self._timeout) as client:
            return client.get(self._base_url, params=params)


def _list_of_objects(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, dict)]


def _meta_code(payload: JsonObject) -> int | None:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None

    code = meta.get("code")
    return code if isinstance(code, int) else None


def _merge_pinned_items(
    pinned_items_by_product_id: dict[str, JsonObject],
    pinned_items: list[JsonObject],
) -> None:
    for item in pinned_items:
        product_id = _product_id(item)
        key = product_id or f"raw:{len(pinned_items_by_product_id)}"
        pinned_items_by_product_id.setdefault(key, item)


def _product_id(item: JsonObject) -> str | None:
    product = item.get("product")
    if not isinstance(product, dict):
        return None

    product_id = product.get("id")
    return product_id if isinstance(product_id, str) else None


def _completeness(
    *,
    pages: list[TwogisBranchPage],
    item_count: int,
    total: int | None,
    stop_reason: str,
) -> str:
    if not pages:
        return "empty"

    if item_count == 0:
        return "empty"

    if total is None:
        return "complete" if stop_reason == "empty_page" else "partial"

    if stop_reason == "source_total_reached":
        return "complete"

    if item_count >= total:
        return "complete"

    return "partial"
