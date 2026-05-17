from datetime import UTC, datetime

import scripts.report_scrape_runs as report_scrape_runs


def test_format_run_includes_shop_status_counts_and_metadata() -> None:
    line = report_scrape_runs._format_run(
        report_scrape_runs.ScrapeRunSummary(
            id=12,
            source="2gis",
            shop_id=5,
            shop_name="Build Shop",
            shop_source_id="branch-1",
            status="partial",
            started_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
            finished_at=datetime(2026, 5, 17, 10, 1, tzinfo=UTC),
            items_seen=50,
            items_saved=48,
            error="",
            completeness="partial",
            stop_reason="max_pages_reached",
            branch_id="branch-1",
        )
    )

    assert line.startswith("scrape run: ")
    assert "id=12" in line
    assert "source=2gis" in line
    assert "shop_id=5" in line
    assert "shop_source_id=branch-1" in line
    assert "shop_name=Build Shop" in line
    assert "status=partial" in line
    assert "started_at=2026-05-17T10:00:00Z" in line
    assert "finished_at=2026-05-17T10:01:00Z" in line
    assert "items_seen=50" in line
    assert "items_saved=48" in line
    assert "error=-" in line
    assert "completeness=partial" in line
    assert "stop_reason=max_pages_reached" in line
    assert "branch_id=branch-1" in line


def test_report_main_forwards_filters_and_prints_runs(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_list_scrape_runs(session: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return [
            report_scrape_runs.ScrapeRunSummary(
                id=1,
                source="2gis",
                shop_id=None,
                shop_name=None,
                shop_source_id=None,
                status="success",
                started_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
                finished_at=None,
                items_seen=3,
                items_saved=3,
                error=None,
                completeness="complete",
                stop_reason="source_total_reached",
                branch_id="branch-1",
            )
        ]

    monkeypatch.setattr(report_scrape_runs, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(report_scrape_runs, "_list_scrape_runs", fake_list_scrape_runs)

    result = report_scrape_runs.main(["--source", "2gis", "--days", "3", "--limit", "10"])

    output = capsys.readouterr().out
    assert result == 0
    assert captured["source"] == "2gis"
    assert captured["days"] == 3
    assert captured["limit"] == 10
    assert "scrape run: id=1" in output
    assert "finished_at=-" in output


def test_report_main_prints_empty_state(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(report_scrape_runs, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(report_scrape_runs, "_list_scrape_runs", lambda session, **kwargs: [])

    result = report_scrape_runs.main([])

    assert result == 0
    assert capsys.readouterr().out == "scrape run summary: no runs found\n"


class FakeSessionLocal:
    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None
