import scripts.report_product_match_candidates as report_product_match_candidates


def test_generate_report_candidates_filters_medium_confidence_candidates() -> None:
    products = [
        _product(id=1, shop_id=10, title="Штукатурка гипсовая Ротбанд KNAUF 30кг"),
        _product(id=2, shop_id=20, title="Штукатурка Ротбанд KNAUF 30кг белая"),
        _product(id=3, shop_id=30, title="Цемент М500 50кг"),
    ]

    candidates = report_product_match_candidates.generate_report_candidates(
        products,
        min_confidence=0.66,
        max_confidence=0.95,
        limit=10,
        allow_category_mismatch=False,
    )

    assert len(candidates) == 1
    assert candidates[0].confidence == 0.667
    assert candidates[0].reason.method == "token_similarity"


def test_format_candidate_includes_confidence_method_and_context() -> None:
    products = [
        _product(id=1, shop_id=10, shop_name="Shop A", title="Цемент М500 50кг"),
        _product(id=2, shop_id=20, shop_name="Shop B", title=" цемент м500 50кг "),
    ]
    candidate = report_product_match_candidates.generate_report_candidates(
        products,
        min_confidence=0.75,
        max_confidence=None,
        limit=10,
        allow_category_mismatch=False,
    )[0]

    line = report_product_match_candidates.format_candidate(
        candidate,
        left=products[0],
        right=products[1],
    )

    assert line == (
        "match candidate: "
        "confidence=1.000 "
        "method=exact_normalized_title "
        "left_id=1 "
        "left_shop=Shop A "
        "left_title=Цемент М500 50кг "
        "right_id=2 "
        "right_shop=Shop B "
        "right_title= цемент м500 50кг  "
        "category_id=1 "
        "category_raw=Сухие смеси"
    )


def test_format_reason_lists_shared_missing_and_ignored_tokens() -> None:
    products = [
        _product(id=1, shop_id=10, title="Клей плиточный КНАУФ Флизен 25кг"),
        _product(id=2, shop_id=20, title="КНАУФ Флизен клей для плитки 25 кг"),
    ]
    candidate = report_product_match_candidates.generate_report_candidates(
        products,
        min_confidence=0.75,
        max_confidence=None,
        limit=10,
        allow_category_mismatch=False,
    )[0]

    line = report_product_match_candidates.format_reason(candidate)

    assert line == (
        "  reason: "
        "matched_normalized_title=- "
        "token_similarity=1.000 "
        "same_category=True "
        "overlap=25кг,клей,кнауф,плиточный,флизен "
        "left_only=- "
        "right_only=- "
        "ignored=для"
    )


def test_report_main_forwards_filters_and_prints_candidates(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}
    products = [
        _product(id=1, shop_id=10, title="Цемент М500 50кг"),
        _product(id=2, shop_id=20, title="Цемент М500 50кг"),
    ]

    def fake_list_active_products(session: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return products

    monkeypatch.setattr(report_product_match_candidates, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(
        report_product_match_candidates,
        "list_active_products",
        fake_list_active_products,
    )

    result = report_product_match_candidates.main(
        [
            "--source",
            "2gis",
            "--shop-id",
            "10",
            "--category-id",
            "1",
            "--category-raw",
            "Сухие смеси",
            "--min-confidence",
            "0.75",
            "--limit",
            "5",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert captured == {
        "source": "2gis",
        "shop_id": 10,
        "category_id": 1,
        "category_raw": "Сухие смеси",
    }
    assert "product match candidate summary: products=2 candidates=1" in output
    assert "match candidate:" in output
    assert "reason:" in output


class FakeSessionLocal:
    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _product(
    *,
    id: int,
    shop_id: int,
    title: str,
    shop_name: str = "Shop",
    category_id: int | None = 1,
    category_raw: str | None = "Сухие смеси",
) -> report_product_match_candidates.MatchReportProduct:
    return report_product_match_candidates.MatchReportProduct(
        id=id,
        source="2gis",
        shop_id=shop_id,
        shop_name=shop_name,
        shop_source_id=f"branch-{shop_id}",
        title=title,
        normalized_title=" ".join(title.casefold().split()),
        category_id=category_id,
        category_raw=category_raw,
    )
