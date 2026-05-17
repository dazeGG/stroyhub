from scripts.setup_data_collection import main


def test_setup_data_collection_dry_run_lists_categories_then_whitelist(capsys) -> None:
    result = main(["--dry-run", "--scrape-interval", "3600"])

    output = capsys.readouterr().out
    assert result == 0
    assert output.index("== Seed normalized categories ==") < output.index(
        "== Seed initial 2GIS whitelist =="
    )
    assert "seed category: slug=mixes_aggregates name=Смеси и сыпучие материалы" in output
    assert "schedule shop: source=2gis" in output
    assert "scrape_interval=3600" in output
