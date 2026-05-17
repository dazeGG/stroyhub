from scripts.seed_categories import main


def test_seed_categories_dry_run_lists_taxonomy(capsys) -> None:
    exit_code = main(["--dry-run"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "seed category: slug=mixes_aggregates name=Смеси и сыпучие материалы" in output
    assert "seed category: slug=cement parent=mixes_aggregates name=Цемент" in output
