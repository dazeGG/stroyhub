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
