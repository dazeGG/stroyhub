import importlib.util
from pathlib import Path
from types import ModuleType

import httpx
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "metalltorg"


def test_metalltorg_cli_prints_scrape_summary(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()

    def fake_fetch_html(url: str, timeout: float) -> str:
        assert url == "https://metalltorg.biz/catalog/stroitelnye_materialy_1/kirpich/"
        assert timeout == 20.0
        return (FIXTURES_DIR / "category-kirpich-page1.html").read_text()

    module._fetch_html = fake_fetch_html

    exit_code = module.main(["--category-slug", "kirpich"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "scrape summary:" in output
    assert "pages=1" in output
    assert "products=1" in output
    assert "priced=1" in output
    assert "failures=0" in output


def test_metalltorg_cli_accepts_direct_url_and_follows_pagination(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()
    pages = {
        "https://example.test/catalog/page1/": """
        <html><body>
          <div class="item_block" data-id="product-1">
            <div class="item-title"><a href="/p1/"><span>Первый товар</span></a></div>
            <div class="price" data-currency="RUB" data-value="10"></div>
          </div>
          <div class="bottom_nav" data-all_count="2">
            <a href="https://example.test/catalog/page2/?PAGEN_1=2">2</a>
          </div>
        </body></html>
        """,
        "https://example.test/catalog/page2/?PAGEN_1=2": """
        <html><body>
          <div class="item_block" data-id="product-2">
            <div class="item-title"><a href="/p2/"><span>Второй товар</span></a></div>
          </div>
        </body></html>
        """,
    }

    def fake_fetch_html(url: str, timeout: float) -> str:
        return pages[url]

    module._fetch_html = fake_fetch_html

    exit_code = module.main(["https://example.test/catalog/page1/", "--max-pages", "2"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "pages=2" in output
    assert "products=2" in output
    assert "priced=1" in output
    assert "next_pages=1" in output


def test_metalltorg_cli_reports_page_failures(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()

    def fake_fetch_html(url: str, timeout: float) -> str:
        raise httpx.ConnectError("offline")

    result = module.scrape_metalltorg_pages(
        start_url="https://example.test/catalog/",
        max_pages=1,
        fetch=fake_fetch_html,
    )

    output = capsys.readouterr().out
    assert result.pages_seen == 0
    assert result.products_parsed == 0
    assert result.failures == 1
    assert "page failure:" in output


def test_metalltorg_cli_rejects_persist_until_persistence_exists() -> None:
    module = _load_cli_module()

    with pytest.raises(SystemExit):
        module.main(["--persist"])


def _load_cli_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "scrape_metalltorg_page.py"
    spec = importlib.util.spec_from_file_location("scrape_metalltorg_page_test_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
