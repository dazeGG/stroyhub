import json

import httpx
import pytest
from stroyhub.parsers.twogis import TwogisClient, TwogisClientError


def test_twogis_client_fetches_branch_page_with_configurable_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/5.0/product/items_by_branch"
        assert request.url.params["branch_id"] == "70000001007229923"
        assert request.url.params["locale"] == "ru_RU"
        assert request.url.params["page"] == "2"
        assert request.url.params["page_size"] == "25"
        return httpx.Response(
            200,
            json={
                "meta": {"code": 200},
                "result": {
                    "total": 106,
                    "updated_at": "Обновлено 13 января 2026",
                    "items": [{"product": {"id": "item-1"}}],
                    "pinned_items": [{"product": {"id": "pinned-1"}}],
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = TwogisClient(client=http_client)

    page = client.fetch_branch_page(
        branch_id="70000001007229923",
        page=2,
        page_size=25,
    )

    assert page.branch_id == "70000001007229923"
    assert page.page == 2
    assert page.page_size == 25
    assert page.total == 106
    assert page.updated_at_raw == "Обновлено 13 января 2026"
    assert page.items == [{"product": {"id": "item-1"}}]
    assert page.pinned_items == [{"product": {"id": "pinned-1"}}]
    assert page.raw["meta"] == {"code": 200}


def test_twogis_client_error_includes_branch_page_and_status() -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    client = TwogisClient(client=http_client)

    with pytest.raises(TwogisClientError) as error:
        client.fetch_branch_page(branch_id="branch-1", page=3)

    message = str(error.value)
    assert "branch_id=branch-1" in message
    assert "page=3" in message
    assert "status=503" in message


def test_twogis_client_rejects_payload_without_result_object() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    )
    client = TwogisClient(client=http_client)

    with pytest.raises(TwogisClientError, match="result object"):
        client.fetch_branch_page(branch_id="branch-1")


def test_twogis_client_uses_meta_code_for_api_errors() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"meta": {"code": 404}}))
    )
    client = TwogisClient(client=http_client)

    with pytest.raises(TwogisClientError) as error:
        client.fetch_branch_page(branch_id="branch-1", page=4)

    message = str(error.value)
    assert "branch_id=branch-1" in message
    assert "page=4" in message
    assert "status=404" in message


def test_twogis_client_rejects_invalid_json() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="{"))
    )
    client = TwogisClient(client=http_client)

    with pytest.raises(TwogisClientError, match="invalid JSON"):
        client.fetch_branch_page(branch_id="branch-1")


def test_twogis_client_ignores_non_object_items() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=json.dumps({"result": {"items": [{"ok": True}, None, "bad"]}}).encode(),
            )
        )
    )
    client = TwogisClient(client=http_client)

    page = client.fetch_branch_page(branch_id="branch-1")

    assert page.items == [{"ok": True}]


def test_twogis_client_fetches_pages_until_source_total_is_reached() -> None:
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_number = int(request.url.params["page"])
        seen_pages.append(page_number)
        items_by_page = {
            1: [{"product": {"id": "1"}}, {"product": {"id": "2"}}],
            2: [{"product": {"id": "3"}}],
        }
        return httpx.Response(
            200,
            json={
                "result": {
                    "total": 3,
                    "items": items_by_page[page_number],
                    "pinned_items": [{"product": {"id": "pinned-1"}}],
                }
            },
        )

    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.fetch_branch_items(branch_id="branch-1", page_size=2)

    assert seen_pages == [1, 2]
    assert [item["product"]["id"] for item in result.items] == ["1", "2", "3"]
    assert result.total == 3
    assert result.stop_reason == "source_total_reached"
    assert result.completeness == "complete"
    assert result.is_complete
    assert not result.is_partial
    assert len(result.pinned_items) == 1


def test_twogis_client_marks_empty_catalog_clearly() -> None:
    client = TwogisClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"result": {"total": 0, "items": []}})
            )
        )
    )

    result = client.fetch_branch_items(branch_id="branch-1")

    assert result.items == []
    assert result.total == 0
    assert result.stop_reason == "source_total_reached"
    assert result.completeness == "empty"


def test_twogis_client_marks_partial_when_empty_page_arrives_before_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page_number = int(request.url.params["page"])
        items = [{"product": {"id": "1"}}] if page_number == 1 else []
        return httpx.Response(200, json={"result": {"total": 3, "items": items}})

    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.fetch_branch_items(branch_id="branch-1", page_size=1)

    assert len(result.items) == 1
    assert result.total == 3
    assert result.stop_reason == "empty_page"
    assert result.completeness == "partial"
    assert result.is_partial


def test_twogis_client_marks_partial_when_max_pages_is_reached() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": {"total": 10, "items": [{"product": {"id": "same-page-size"}}]}},
        )

    client = TwogisClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.fetch_branch_items(branch_id="branch-1", page_size=1, max_pages=2)

    assert len(result.pages) == 2
    assert len(result.items) == 2
    assert result.stop_reason == "max_pages_reached"
    assert result.completeness == "partial"


def test_twogis_client_rejects_invalid_pagination_options() -> None:
    client = TwogisClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )

    with pytest.raises(ValueError, match="page_size"):
        client.fetch_branch_items(branch_id="branch-1", page_size=0)

    with pytest.raises(ValueError, match="max_pages"):
        client.fetch_branch_items(branch_id="branch-1", max_pages=0)
