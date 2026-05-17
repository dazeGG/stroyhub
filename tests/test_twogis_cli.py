import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_twogis_cli_prints_scrape_summary(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()

    def fake_scrape_twogis_branch(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            branch_id=kwargs["branch_id"],
            total=3,
            pages_seen=2,
            items_seen=3,
            products=[
                SimpleNamespace(price=100),
                SimpleNamespace(price=None),
                SimpleNamespace(price=200),
            ],
            pinned_items_seen=1,
            completeness="complete",
            stop_reason="source_total_reached",
        )

    module.scrape_twogis_branch = fake_scrape_twogis_branch

    exit_code = module.main(["branch-1", "--page-size", "2", "--max-pages", "10"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "scrape summary:" in output
    assert "branch_id=branch-1" in output
    assert "items=3" in output
    assert "parsed=3" in output
    assert "priced=2" in output
    assert "completeness=complete" in output


def test_twogis_cli_can_optionally_persist(capsys) -> None:  # type: ignore[no-untyped-def]
    module = _load_cli_module()

    def fake_scrape_twogis_branch(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            branch_id=kwargs["branch_id"],
            total=1,
            pages_seen=1,
            items_seen=1,
            products=[SimpleNamespace(price=100)],
            pinned_items_seen=0,
            completeness="complete",
            stop_reason="source_total_reached",
        )

    def fake_persist_twogis_scrape_result(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            shop_id=10,
            scrape_run_id=20,
            source_products_saved=1,
            price_snapshots_saved=1,
            scrape_status="success",
        )

    module.scrape_twogis_branch = fake_scrape_twogis_branch
    module.persist_twogis_scrape_result = fake_persist_twogis_scrape_result
    module.SessionLocal = FakeSessionLocal

    exit_code = module.main(["branch-1", "--persist", "--shop-name", "Test Shop"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "persist summary:" in output
    assert "shop_id=10" in output
    assert "price_snapshots_saved=1" in output


class FakeSessionLocal:
    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        return None


def _load_cli_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "scrape_twogis_shop.py"
    spec = importlib.util.spec_from_file_location("scrape_twogis_shop_test_module", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
