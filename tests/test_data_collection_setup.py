import subprocess
import sys
from pathlib import Path

from scripts.setup_data_collection import main


def test_setup_data_collection_dry_run_lists_categories_then_candidate_review(capsys) -> None:
    result = main(["--dry-run", "--scrape-interval", "3600"])

    output = capsys.readouterr().out
    assert result == 0
    assert output.index("== Seed normalized categories ==") < output.index(
        "== Seed official Unicom source =="
    )
    assert output.index("== Seed official Unicom source ==") < output.index(
        "== Seed official Metalltorg source =="
    )
    assert output.index("== Seed official Metalltorg source ==") < output.index(
        "== 2GIS candidates are approved through admin candidate review =="
    )
    assert "seed category: slug=mixes_aggregates name=Смеси и сыпучие материалы" in output
    assert "schedule shop: source=unicom" in output
    assert "schedule shop: source=metalltorg" in output
    assert "schedule shop: source=2gis" not in output
    assert "scrape_interval=3600" in output


def test_setup_data_collection_script_runs_documented_dry_run_command() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "scripts/setup_data_collection.py", "--dry-run"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "== Seed normalized categories ==" in result.stdout
    assert "== Seed official Unicom source ==" in result.stdout
    assert "== Seed official Metalltorg source ==" in result.stdout
    assert "== 2GIS candidates are approved through admin candidate review ==" in result.stdout
    assert "schedule shop: source=2gis" not in result.stdout
    assert result.stderr == ""
