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
