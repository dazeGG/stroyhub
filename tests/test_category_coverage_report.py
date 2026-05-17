import scripts.report_category_coverage as report_category_coverage


def test_group_uncategorized_products_by_source_shop_and_raw_category() -> None:
    products = [
        _product(shop_id=1, shop_name="Shop A", category_raw="Raw A", title="First"),
        _product(shop_id=1, shop_name="Shop A", category_raw="Raw A", title="Second"),
        _product(shop_id=2, shop_name="Shop B", category_raw=None, title="Third"),
    ]

    groups = report_category_coverage.group_uncategorized_products(
        products,
        titles_per_group=1,
    )

    assert len(groups) == 2
    assert groups[0].shop_id == 1
    assert groups[0].category_raw == "Raw A"
    assert groups[0].count == 2
    assert groups[0].titles == ("First",)
    assert groups[1].shop_id == 2
    assert groups[1].category_raw is None
    assert groups[1].count == 1


def test_format_group_includes_shop_raw_category_and_count() -> None:
    line = report_category_coverage._format_group(
        report_category_coverage.UncategorizedGroup(
            source="2gis",
            shop_id=7,
            shop_name="Build Shop",
            shop_source_id="branch-1",
            category_raw=None,
            count=5,
            titles=("Example",),
        )
    )

    assert line == (
        "uncategorized group: "
        "source=2gis "
        "shop_id=7 "
        "shop_source_id=branch-1 "
        "shop_name=Build Shop "
        "category_raw=- "
        "count=5"
    )


def test_report_main_forwards_filters_and_prints_representative_titles(
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_list_uncategorized_products(session: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return [
            _product(shop_id=1, shop_name="Shop A", category_raw="Raw A", title="First"),
            _product(shop_id=1, shop_name="Shop A", category_raw="Raw A", title="Second"),
        ]

    monkeypatch.setattr(report_category_coverage, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(
        report_category_coverage,
        "_list_uncategorized_products",
        fake_list_uncategorized_products,
    )

    result = report_category_coverage.main(
        [
            "--source",
            "2gis",
            "--shop-id",
            "1",
            "--limit-groups",
            "10",
            "--titles-per-group",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert captured == {"source": "2gis", "shop_id": 1}
    assert (
        "category coverage summary: uncategorized_products=2 groups=1 groups_displayed=1"
        in output
    )
    assert "uncategorized group:" in output
    assert "category_raw=Raw A" in output
    assert "  title: First" in output
    assert "Second" not in output


class FakeSessionLocal:
    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _product(
    *,
    shop_id: int,
    shop_name: str,
    category_raw: str | None,
    title: str,
) -> report_category_coverage.UncategorizedProduct:
    return report_category_coverage.UncategorizedProduct(
        source="2gis",
        shop_id=shop_id,
        shop_name=shop_name,
        shop_source_id=f"branch-{shop_id}",
        category_raw=category_raw,
        title=title,
    )
