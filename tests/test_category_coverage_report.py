from decimal import Decimal

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


def test_calculate_quality_metrics_counts_coverage_low_confidence_and_raw_categories() -> None:
    products = [
        _quality_product(category_id=1, category_raw="Raw A", confidence=Decimal("0.90")),
        _quality_product(category_id=2, category_raw="Raw A", confidence=Decimal("0.50")),
        _quality_product(category_id=None, category_raw="Raw B", confidence=None),
    ]

    metrics = report_category_coverage.calculate_quality_metrics(
        products,
        low_confidence_threshold=Decimal("0.70"),
        raw_category_limit=10,
    )

    assert metrics.total_products == 3
    assert metrics.categorized_products == 2
    assert metrics.uncategorized_products == 1
    assert metrics.coverage_pct == Decimal("66.67")
    assert metrics.low_confidence_products == 1
    assert metrics.top_raw_categories[0] == report_category_coverage.RawCategoryMetric(
        source="2gis",
        category_raw="Raw A",
        count=2,
        categorized_count=2,
        uncategorized_count=0,
    )


def test_report_main_forwards_filters_and_prints_representative_titles(
    monkeypatch,
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_list_active_products(session: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return [
            _quality_product(
                shop_id=1,
                shop_name="Shop A",
                category_raw="Raw A",
                title="First",
                category_id=None,
            ),
            _quality_product(
                shop_id=1,
                shop_name="Shop A",
                category_raw="Raw A",
                title="Second",
                category_id=7,
                confidence=Decimal("0.55"),
            ),
        ]

    monkeypatch.setattr(report_category_coverage, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(
        report_category_coverage,
        "_list_active_products",
        fake_list_active_products,
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
            "--low-confidence-threshold",
            "0.70",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert captured == {"source": "2gis", "shop_id": 1}
    assert (
        "category quality summary: "
        "total_products=2 "
        "categorized_products=1 "
        "uncategorized_products=1 "
        "coverage_pct=50.00 "
        "low_confidence_products=1 "
        "low_confidence_threshold=0.70"
    ) in output
    assert (
        "top raw category: "
        "source=2gis "
        "category_raw=Raw A "
        "count=2 "
        "categorized=1 "
        "uncategorized=1"
    ) in output
    assert (
        "category coverage summary: uncategorized_products=1 groups=1 groups_displayed=1"
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


def _quality_product(
    *,
    category_raw: str | None,
    category_id: int | None,
    shop_id: int = 1,
    shop_name: str = "Shop A",
    title: str = "Product",
    confidence: Decimal | None = None,
) -> report_category_coverage.CategoryQualityProduct:
    return report_category_coverage.CategoryQualityProduct(
        source="2gis",
        shop_id=shop_id,
        shop_name=shop_name,
        shop_source_id=f"branch-{shop_id}",
        category_raw=category_raw,
        title=title,
        category_id=category_id,
        category_confidence=confidence,
    )
