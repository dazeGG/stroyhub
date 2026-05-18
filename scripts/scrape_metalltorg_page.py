#!/usr/bin/env python

import argparse
from collections.abc import Callable, Sequence

import httpx
from stroyhub.parsers.metalltorg import METALLTORG_BASE_URL, parse_listing_page

DEFAULT_CATEGORY_SLUG = "stroitelnye-materialy"
CATEGORY_URLS = {
    "stroitelnye-materialy": f"{METALLTORG_BASE_URL}/catalog/stroitelnye_materialy_1/",
    "gipsokarton": (
        f"{METALLTORG_BASE_URL}/catalog/stroitelnye_materialy_1/"
        "gipsokarton_i_komplektuyushchie/"
    ),
    "kirpich": f"{METALLTORG_BASE_URL}/catalog/stroitelnye_materialy_1/kirpich/",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Metalltorg category HTML without Celery.")
    parser.add_argument("url", nargs="?")
    parser.add_argument(
        "--category-slug",
        choices=sorted(CATEGORY_URLS),
        default=None,
        help=(
            f"Configured category slug. Defaults to {DEFAULT_CATEGORY_SLUG!r} "
            "when URL is omitted."
        ),
    )
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args(argv)

    if args.persist:
        parser.error("Metalltorg persistence is not implemented; omit --persist for debug parsing.")

    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")

    start_url = _start_url(url=args.url, category_slug=args.category_slug)
    result = scrape_metalltorg_pages(
        start_url=start_url,
        max_pages=args.max_pages,
        timeout=args.timeout,
    )

    print(
        "scrape summary: "
        f"url={start_url} "
        f"pages={result.pages_seen} "
        f"products={result.products_parsed} "
        f"priced={result.priced_products} "
        f"failures={result.failures} "
        f"next_pages={result.next_pages_seen}"
    )
    return 0


class MetalltorgDebugResult:
    def __init__(
        self,
        *,
        pages_seen: int,
        products_parsed: int,
        priced_products: int,
        failures: int,
        next_pages_seen: int,
    ) -> None:
        self.pages_seen = pages_seen
        self.products_parsed = products_parsed
        self.priced_products = priced_products
        self.failures = failures
        self.next_pages_seen = next_pages_seen


def scrape_metalltorg_pages(
    *,
    start_url: str,
    max_pages: int,
    timeout: float = 20.0,
    fetch: Callable[[str, float], str] | None = None,
) -> MetalltorgDebugResult:
    fetch_html = fetch or _fetch_html
    seen_urls: set[str] = set()
    pending_urls = [start_url]
    pages_seen = 0
    products_parsed = 0
    priced_products = 0
    failures = 0
    next_pages_seen = 0

    while pending_urls and pages_seen < max_pages:
        url = pending_urls.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        try:
            html = fetch_html(url, timeout)
        except httpx.HTTPError as exc:
            failures += 1
            print(f"page failure: url={url} error={type(exc).__name__}: {exc}")
            continue

        page = parse_listing_page(html, page_url=url)
        pages_seen += 1
        products_parsed += len(page.products)
        priced_products += sum(1 for product in page.products if product.price is not None)

        for next_url in page.next_page_urls:
            if next_url not in seen_urls and next_url not in pending_urls:
                pending_urls.append(next_url)
                next_pages_seen += 1

    return MetalltorgDebugResult(
        pages_seen=pages_seen,
        products_parsed=products_parsed,
        priced_products=priced_products,
        failures=failures,
        next_pages_seen=next_pages_seen,
    )


def _start_url(*, url: str | None, category_slug: str | None) -> str:
    if url is not None:
        return url
    return CATEGORY_URLS[category_slug or DEFAULT_CATEGORY_SLUG]


def _fetch_html(url: str, timeout: float) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    return response.text


if __name__ == "__main__":
    raise SystemExit(main())
