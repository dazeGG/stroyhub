import json
from pathlib import Path

import httpx
import pytest
from stroyhub.parsers.unicom import UnicomClient, UnicomClientError

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "unicom"


def _load_fixture(name: str) -> object:
    return json.loads((FIXTURES_DIR / name).read_text())


def test_unicom_client_fetches_catalog_menu() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/catalog-menu-2.php"
        return httpx.Response(200, json=_load_fixture("catalog-menu-excerpt.json"))

    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    categories = client.fetch_catalog_menu()

    assert [category.name for category in categories] == [
        "Строительство конструкций",
        "Сухие строительные смеси",
    ]
    assert categories[0].uuid == "e6b7f2dc3d5511e8af077062b8b53ba3"
    assert not categories[0].is_leaf
    assert categories[0].children[0].name == "Блоки строительные"
    assert categories[0].children[0].is_leaf
    assert categories[0].children[1].children[0].name == "ОСП"
    assert categories[1].children[0].uuid == "d68e4fb83d4d11e8af077062b8b53ba3"


def test_unicom_client_fetches_leaf_category_uuids_without_duplicates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/catalog-menu-2.php"
        return httpx.Response(200, json=_load_fixture("catalog-menu-excerpt.json"))

    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert client.fetch_leaf_category_uuids() == (
        "fac247f1ae6111eca255000c29d1f857",
        "9ad35f1538fe11efa2a0000c29d1f857",
        "d68e4fb83d4d11e8af077062b8b53ba3",
    )


def test_unicom_client_fetches_product_page_with_configurable_params() -> None:
    category_uuid = "d68e4fb83d4d11e8af077062b8b53ba3"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api2/v-catalog-beta/products/{category_uuid}"
        assert request.url.params["shop"] == "uc"
        assert request.url.params["page"] == "2"
        assert request.url.params["sort"] == "price"
        assert request.url.params["limit"] == "25"
        return httpx.Response(200, json=_load_fixture("products-cement-page1.json"))

    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    page = client.fetch_product_page(
        category_uuid=category_uuid,
        page=2,
        limit=25,
        sort="price",
    )

    assert page.category_uuid == category_uuid
    assert page.page == 2
    assert page.limit == 25
    assert page.sort == "price"
    assert page.shop == "uc"
    assert page.pages == 1
    assert page.products_count == 2
    assert len(page.products) == 2
    assert page.products[0]["name"] == "Цемент М-400 50кг."
    assert len(page.stocks) == 3
    assert len(page.filters) == 1


def test_unicom_client_can_omit_shop_param() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "shop" not in request.url.params
        return httpx.Response(200, json={"products": [], "pages": 1, "productsCount": 0})

    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    page = client.fetch_product_page(category_uuid="category-1", shop=None)

    assert page.shop is None
    assert page.products == []
    assert page.products_count == 0


def test_unicom_client_error_includes_category_page_and_status() -> None:
    client = UnicomClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    )

    with pytest.raises(UnicomClientError) as error:
        client.fetch_product_page(category_uuid="category-1", page=3)

    message = str(error.value)
    assert "category_uuid=category-1" in message
    assert "page=3" in message
    assert "status=503" in message


def test_unicom_client_rejects_invalid_json() -> None:
    client = UnicomClient(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="{"))
        )
    )

    with pytest.raises(UnicomClientError, match="invalid JSON"):
        client.fetch_product_page(category_uuid="category-1", page=3)


def test_unicom_client_fetches_category_products_until_source_pages_reached() -> None:
    seen_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_number = int(request.url.params["page"])
        seen_pages.append(page_number)
        return httpx.Response(
            200,
            json={
                "products": [{"uuid": f"product-{page_number}"}],
                "pages": 2,
                "productsCount": 2,
            },
        )

    client = UnicomClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.fetch_category_products(
        category_uuid="category-1",
        limit=1,
        max_pages=5,
    )

    assert seen_pages == [1, 2]
    assert [product["uuid"] for product in result.products] == ["product-1", "product-2"]
    assert result.stop_reason == "source_pages_reached"
    assert result.completeness == "complete"
    assert result.is_complete
    assert not result.is_partial


def test_unicom_client_marks_partial_when_max_pages_is_reached() -> None:
    client = UnicomClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "products": [{"uuid": "product"}],
                        "pages": 10,
                        "productsCount": 10,
                    },
                )
            )
        )
    )

    result = client.fetch_category_products(category_uuid="category-1", max_pages=2)

    assert len(result.pages) == 2
    assert len(result.products) == 2
    assert result.stop_reason == "max_pages_reached"
    assert result.completeness == "partial"


def test_unicom_client_rejects_invalid_pagination_options() -> None:
    client = UnicomClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )

    with pytest.raises(ValueError, match="page"):
        client.fetch_product_page(category_uuid="category-1", page=0)

    with pytest.raises(ValueError, match="limit"):
        client.fetch_product_page(category_uuid="category-1", limit=0)

    with pytest.raises(ValueError, match="max_pages"):
        client.fetch_category_products(category_uuid="category-1", max_pages=0)
