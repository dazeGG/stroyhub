from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from stroyhub.parsers.common import (
    JsonObject,
    ParsedProduct,
    build_fingerprint,
    normalize_title,
    parse_decimal,
)

METALLTORG_SOURCE = "metalltorg"
METALLTORG_BASE_URL = "https://metalltorg.biz"
METALLTORG_SHOP_SOURCE_ID = "metalltorg-yakutsk"
METALLTORG_DEFAULT_CURRENCY = "RUB"

PRODUCT_CARD_SELECTOR = "item_block"
TITLE_SELECTOR = "item-title"
PRICE_SELECTOR = "price"
UNIT_SELECTOR = "price_measure"
IMAGE_ATTR = "data-src"
ARTICLE_ATTR = "data-value"
PAGINATION_QUERY = "PAGEN_1="
TOTAL_COUNT_ATTR = "data-all_count"


@dataclass(frozen=True, kw_only=True)
class MetalltorgListingPage:
    products: list[ParsedProduct]
    next_page_urls: list[str]
    total_count: int | None
    raw: JsonObject


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: "_Node | None" = None
    children: list["_Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        chunks = [*self.text_parts]
        for child in self.children:
            chunks.append(child.text)
        return " ".join(part.strip() for part in chunks if part.strip())


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="document", attrs={})
        self._stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag=tag,
            attrs={key: value or "" for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag=tag,
            attrs={key: value or "" for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._stack[-1].text_parts.append(data)


def parse_listing_page(
    html: str,
    *,
    category_raw: str | None = None,
    page_url: str = METALLTORG_BASE_URL,
    parsed_at: datetime | None = None,
) -> MetalltorgListingPage:
    root = _parse_tree(html)
    observed_at = parsed_at or datetime.now(UTC)
    resolved_category = category_raw or _page_heading(root)
    card_nodes = _find_all(root, lambda node: _has_class(node, PRODUCT_CARD_SELECTOR))
    card_html_by_id = _card_html_by_id(html)
    products = [
        product
        for card in card_nodes
        if (
            product := _parse_card(
                card,
                category_raw=resolved_category,
                page_url=page_url,
                parsed_at=observed_at,
                card_html=card_html_by_id.get(card.attrs.get("data-id", "")),
            )
        )
        is not None
    ]

    return MetalltorgListingPage(
        products=products,
        next_page_urls=_next_page_urls(root, page_url=page_url),
        total_count=_total_count(root),
        raw={
            "page_url": page_url,
            "category_raw": resolved_category,
            "product_cards_seen": len(card_nodes),
        },
    )


def _parse_card(
    card: _Node,
    *,
    category_raw: str | None,
    page_url: str,
    parsed_at: datetime,
    card_html: str | None,
) -> ParsedProduct | None:
    title_node = _first_descendant(card, lambda node: _has_class(node, TITLE_SELECTOR))
    title_link = _first_descendant(title_node, lambda node: node.tag == "a") if title_node else None
    title = _clean_text(title_node.text if title_node else "")
    if not title:
        return None

    product_url = _absolute_url(_attr(title_link, "href"), page_url=page_url)
    source_product_id = _clean_text(card.attrs.get("data-id", "")) or _id_from_url(product_url)
    price_node = _first_descendant(card, lambda node: _has_class(node, PRICE_SELECTOR))
    unit_node = _first_descendant(card, lambda node: _has_class(node, UNIT_SELECTOR))
    article_node = _first_descendant(
        card,
        lambda node: _has_class(node, "article_block") and bool(node.attrs.get(ARTICLE_ATTR)),
    )
    image_node = _first_descendant(card, lambda node: node.tag == "img")
    image_url = _image_url(image_node, page_url=page_url)
    normalized_title = normalize_title(title)
    unit_raw = _unit_raw(unit_node.text if unit_node else None)

    return ParsedProduct(
        source=METALLTORG_SOURCE,
        shop_source_id=METALLTORG_SHOP_SOURCE_ID,
        source_product_id=source_product_id,
        title=title,
        normalized_title=normalized_title,
        description=None,
        category_raw=category_raw,
        unit_raw=unit_raw,
        price=parse_decimal(_attr(price_node, "data-value")),
        currency=_attr(price_node, "data-currency") or METALLTORG_DEFAULT_CURRENCY,
        image_url=image_url,
        source_updated_at=None,
        fingerprint=build_fingerprint(normalized_title, unit_raw, category_raw),
        raw={
            "source_product_id": source_product_id,
            "product_url": product_url,
            "article": _attr(article_node, ARTICLE_ATTR),
            "stock_text": _stock_text(card),
            "card_text": card.text,
            "card_html": card_html,
        },
        parsed_at=parsed_at,
    )


def _parse_tree(html: str) -> _Node:
    parser = _TreeParser()
    parser.feed(html)
    return parser.root


def _find_all(node: _Node, predicate: Any) -> list[_Node]:
    matches = [node] if predicate(node) else []
    for child in node.children:
        matches.extend(_find_all(child, predicate))
    return matches


def _first_descendant(node: _Node | None, predicate: Any) -> _Node | None:
    if node is None:
        return None
    for match in _find_all(node, predicate):
        if match is not node:
            return match
    return None


def _has_class(node: _Node, class_name: str) -> bool:
    return class_name in node.attrs.get("class", "").split()


def _attr(node: _Node | None, name: str) -> str | None:
    if node is None:
        return None
    value = node.attrs.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(unescape(value).split())
    return cleaned or None


def _unit_raw(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return cleaned.removeprefix("/").strip() or None


def _absolute_url(value: str | None, *, page_url: str) -> str | None:
    if value is None:
        return None
    return urljoin(page_url, value)


def _image_url(node: _Node | None, *, page_url: str) -> str | None:
    image = _attr(node, IMAGE_ATTR) or _attr(node, "src")
    if image is None or image.startswith("data:image/") or "noimage_product.svg" in image:
        return None
    return urljoin(page_url, image)


def _id_from_url(url: str | None) -> str | None:
    if url is None:
        return None
    parts = [part for part in url.rstrip("/").split("/") if part]
    if not parts:
        return None
    last = parts[-1]
    return last if last.isdecimal() else None


def _stock_text(card: _Node) -> str | None:
    stock_node = _first_descendant(card, lambda node: _has_class(node, "item-stock"))
    if stock_node is None:
        return None
    return _clean_text(stock_node.text)


def _page_heading(root: _Node) -> str | None:
    heading = _first_descendant(root, lambda node: node.tag == "h1")
    return _clean_text(heading.text if heading else None)


def _next_page_urls(root: _Node, *, page_url: str) -> list[str]:
    urls: list[str] = []
    for link in _find_all(root, lambda node: node.tag == "a"):
        href = _attr(link, "href")
        if href is not None and PAGINATION_QUERY in href:
            urls.append(urljoin(page_url, href))
    return sorted(set(urls))


def _total_count(root: _Node) -> int | None:
    node = _first_descendant(root, lambda item: TOTAL_COUNT_ATTR in item.attrs)
    if node is None:
        return None
    value = node.attrs.get(TOTAL_COUNT_ATTR)
    if value is None or not value.isdecimal():
        return None
    return int(value)


def _card_html_by_id(html: str) -> dict[str, str]:
    result: dict[str, str] = {}
    marker = " item_block"
    position = 0
    while True:
        marker_index = html.find(marker, position)
        if marker_index == -1:
            break
        start = html.rfind("<div", 0, marker_index)
        if start == -1:
            position = marker_index + len(marker)
            continue
        next_marker = html.find(marker, marker_index + len(marker))
        end = html.rfind("<div", marker_index, next_marker) if next_marker != -1 else -1
        if end == -1 or end <= start:
            end = min(len(html), start + 12000)
        snippet = html[start:end]
        source_id = _source_id_from_html(snippet)
        if source_id is not None:
            result[source_id] = snippet
        position = marker_index + len(marker)
    return result


def _source_id_from_html(html: str) -> str | None:
    needle = 'data-id="'
    start = html.find(needle)
    if start == -1:
        return None
    start += len(needle)
    end = html.find('"', start)
    if end == -1:
        return None
    value = html[start:end].strip()
    return value or None
