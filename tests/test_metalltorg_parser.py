from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from stroyhub.parsers.metalltorg import parse_listing_page

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "metalltorg"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text()


def test_parse_listing_page_maps_product_card_to_parsed_product() -> None:
    parsed_at = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)

    page = parse_listing_page(
        _load_fixture("category-kirpich-page1.html"),
        page_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/",
        parsed_at=parsed_at,
    )

    assert page.total_count == 1
    assert page.next_page_urls == []
    assert page.raw["product_cards_seen"] == 1
    assert len(page.products) == 1

    product = page.products[0]
    assert product.source == "metalltorg"
    assert product.shop_source_id == "metalltorg-yakutsk"
    assert product.source_product_id == "120420"
    assert product.title == "Кирпич огнеупорный полнотелый ШБ-5 (65х114х230) 1/385шт ГОСТ 390-96"
    assert product.category_raw == "Кирпич"
    assert product.price == Decimal("195")
    assert product.currency == "RUB"
    assert product.unit_raw == "шт"
    assert product.image_url == (
        "https://metalltorg.biz/upload/iblock/c5c/s41xll7ischkprv2hylspondydvipevh.jpg"
    )
    assert product.source_updated_at is None
    assert product.parsed_at == parsed_at
    assert product.fingerprint is not None
    assert product.raw["product_url"] == (
        "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/120420/"
    )
    assert product.raw["article"] == "24407"
    assert product.raw["stock_text"] == "Достаточно"
    assert product.raw["card_html"] is not None


def test_parse_listing_page_handles_missing_price_image_and_explicit_category() -> None:
    html = """
    <html>
      <body>
        <div class="items">
          <div class="item_block" data-id="no-price">
            <a href="/catalog/no-price/" class="thumb shine">
              <img src="data:image/gif;base64,placeholder" />
            </a>
            <div class="item-title">
              <a href="/catalog/no-price/" class="dark_link"><span>Товар без цены</span></a>
            </div>
          </div>
        </div>
      </body>
    </html>
    """

    page = parse_listing_page(
        html,
        category_raw="Тестовая категория",
        page_url="https://metalltorg.biz/catalog/test/",
    )

    product = page.products[0]
    assert product.source_product_id == "no-price"
    assert product.category_raw == "Тестовая категория"
    assert product.price is None
    assert product.unit_raw is None
    assert product.image_url is None


def test_parse_listing_page_collects_pagination_links_and_total_count() -> None:
    html = """
    <html>
      <body>
        <h1>Строительные материалы</h1>
        <div class="bottom_nav" data-all_count="1185">
          <div class="module-pagination">
            <a href="/catalog/stroitelnye_materialy_1/?PAGEN_1=2">2</a>
            <a href="/catalog/stroitelnye_materialy_1/?PAGEN_1=60">60</a>
          </div>
        </div>
      </body>
    </html>
    """

    page = parse_listing_page(
        html,
        page_url="https://metalltorg.biz/catalog/stroitelnye_materialy_1/",
    )

    assert page.total_count == 1185
    assert page.next_page_urls == [
        "https://metalltorg.biz/catalog/stroitelnye_materialy_1/?PAGEN_1=2",
        "https://metalltorg.biz/catalog/stroitelnye_materialy_1/?PAGEN_1=60",
    ]
    assert page.raw["category_raw"] == "Строительные материалы"


def test_parse_listing_page_skips_cards_without_title() -> None:
    page = parse_listing_page('<div class="item_block" data-id="missing-title"></div>')

    assert page.products == []
    assert page.raw["product_cards_seen"] == 1
