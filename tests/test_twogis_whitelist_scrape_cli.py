import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_twogis_whitelist_scrape_cli_persists_all_listed_shops(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()
    shops = [
        SimpleNamespace(id=1, source_id="branch-1", name="Shop One"),
        SimpleNamespace(id=2, source_id="branch-2", name="Shop Two"),
    ]
    scraped_branch_ids: list[str] = []
    completed_shop_ids: list[int] = []

    def fake_scrape_twogis_branch(**kwargs: object) -> SimpleNamespace:
        scraped_branch_ids.append(str(kwargs["branch_id"]))
        return SimpleNamespace(
            branch_id=kwargs["branch_id"],
            total=2,
            pages_seen=1,
            items_seen=2,
            products=[object(), object()],
            completeness="complete",
            stop_reason="source_total_reached",
        )

    def fake_persist_twogis_scrape_result(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            source_products_saved=2,
            price_snapshots_saved=2,
            scrape_status="success",
        )

    def fake_mark_shop_scrape_completion(shop: object, **kwargs: object) -> None:
        completed_shop_ids.append(shop.id)  # type: ignore[attr-defined]

    module.SessionLocal = FakeSessionLocal
    module._list_whitelisted_twogis_shops = lambda session, *, limit: shops
    module.scrape_twogis_branch = fake_scrape_twogis_branch
    module.persist_twogis_scrape_result = fake_persist_twogis_scrape_result
    module.mark_shop_scrape_completion = fake_mark_shop_scrape_completion

    exit_code = module.main([])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert scraped_branch_ids == ["branch-1", "branch-2"]
    assert completed_shop_ids == [1, 2]
    assert output.count("shop scrape summary:") == 2
    assert "whitelist scrape summary:" in output
    assert "shops_total=2" in output
    assert "shops_scraped=2" in output
    assert "shops_partial=0" in output
    assert "source_products_saved=4" in output
    assert "price_snapshots_saved=4" in output


def test_twogis_whitelist_scrape_cli_records_failures_and_continues(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()
    shops = [
        SimpleNamespace(id=1, source_id="branch-ok", name="Shop One"),
        SimpleNamespace(id=2, source_id="branch-fail", name="Shop Two"),
    ]
    failed_shop_ids: list[int] = []

    def fake_scrape_twogis_branch(**kwargs: object) -> SimpleNamespace:
        if kwargs["branch_id"] == "branch-fail":
            raise RuntimeError("timeout")
        return SimpleNamespace(
            branch_id=kwargs["branch_id"],
            total=1,
            pages_seen=1,
            items_seen=1,
            products=[object()],
            completeness="complete",
            stop_reason="source_total_reached",
        )

    def fake_persist_twogis_scrape_result(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            source_products_saved=1,
            price_snapshots_saved=1,
            scrape_status="success",
        )

    def fake_mark_shop_scrape_failure(shop: object, **kwargs: object) -> None:
        failed_shop_ids.append(shop.id)  # type: ignore[attr-defined]

    session = FakeSessionLocal()
    session.shops_by_id = {shop.id: shop for shop in shops}
    module.SessionLocal = lambda: session
    module._list_whitelisted_twogis_shops = lambda session, *, limit: shops
    module.scrape_twogis_branch = fake_scrape_twogis_branch
    module.persist_twogis_scrape_result = fake_persist_twogis_scrape_result
    module.mark_shop_scrape_completion = lambda shop, **kwargs: None
    module.mark_shop_scrape_failure = fake_mark_shop_scrape_failure

    exit_code = module.main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert failed_shop_ids == [2]
    assert "shop scrape failure:" in output
    assert "error=timeout" in output
    assert "shops_total=2" in output
    assert "shops_scraped=1" in output
    assert "shops_partial=0" in output
    assert "shops_failed=1" in output


def test_twogis_whitelist_scrape_cli_returns_failure_for_partial_scrapes(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()
    shops = [SimpleNamespace(id=1, source_id="branch-partial", name="Partial Shop")]

    def fake_scrape_twogis_branch(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            branch_id=kwargs["branch_id"],
            total=100,
            pages_seen=1,
            items_seen=50,
            products=[object()],
            completeness="partial",
            stop_reason="max_pages_reached",
        )

    def fake_persist_twogis_scrape_result(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            source_products_saved=1,
            price_snapshots_saved=1,
            scrape_status="partial",
        )

    module.SessionLocal = FakeSessionLocal
    module._list_whitelisted_twogis_shops = lambda session, *, limit: shops
    module.scrape_twogis_branch = fake_scrape_twogis_branch
    module.persist_twogis_scrape_result = fake_persist_twogis_scrape_result
    module.mark_shop_scrape_completion = lambda shop, **kwargs: None

    exit_code = module.main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "shop scrape summary:" in output
    assert "scrape_status=partial" in output
    assert "shops_scraped=1" in output
    assert "shops_partial=1" in output
    assert "shops_failed=0" in output


class FakeSessionLocal:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.shops_by_id: dict[int, object] = {}

    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def get(self, model: object, shop_id: int) -> object | None:
        return self.shops_by_id.get(shop_id)


def _load_cli_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "scrape_twogis_whitelist.py"
    spec = importlib.util.spec_from_file_location(
        "scrape_twogis_whitelist_test_module",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
