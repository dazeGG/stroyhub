from dataclasses import dataclass

import scripts.backfill_category_ids as backfill_category_ids


def test_backfill_products_updates_category_when_prediction_is_available() -> None:
    product = _product(title="Цемент М500", category_id=None)

    result = backfill_category_ids.backfill_products(
        [product],
        category_repository=FakeCategoryRepository(),
        categorizer=backfill_category_ids.RuleBasedCategorizer(),
        dry_run=False,
    )

    assert result.products_seen == 1
    assert result.changed == 1
    assert result.unchanged == 0
    assert result.unmatched == 0
    assert product.category_id == 2


def test_backfill_products_dry_run_reports_change_without_mutating_product() -> None:
    product = _product(title="Цемент М500", category_id=None)

    result = backfill_category_ids.backfill_products(
        [product],
        category_repository=FakeCategoryRepository(),
        categorizer=backfill_category_ids.RuleBasedCategorizer(),
        dry_run=True,
    )

    assert result.changed == 1
    assert result.dry_run is True
    assert product.category_id is None


def test_backfill_products_counts_unchanged_and_unmatched_products() -> None:
    products = [
        _product(title="Цемент М500", category_id=2),
        _product(title="Подарочный сертификат", category_id=None),
    ]

    result = backfill_category_ids.backfill_products(
        products,
        category_repository=FakeCategoryRepository(),
        categorizer=backfill_category_ids.RuleBasedCategorizer(),
        dry_run=False,
    )

    assert result.products_seen == 2
    assert result.changed == 0
    assert result.unchanged == 1
    assert result.unmatched == 1


def test_backfill_products_skips_active_category_overrides() -> None:
    product = _product(title="Цемент М500", category_id=None)
    product.category_overrides = [FakeOverride(status="active")]

    result = backfill_category_ids.backfill_products(
        [product],
        category_repository=FakeCategoryRepository(),
        categorizer=backfill_category_ids.RuleBasedCategorizer(),
        dry_run=False,
    )

    assert result.products_seen == 1
    assert result.changed == 0
    assert result.unchanged == 1
    assert result.unmatched == 0
    assert product.category_id is None


def test_backfill_products_does_not_lazy_load_unloaded_category_overrides() -> None:
    product = LazyOverrideProduct(title="Цемент М500", category_id=None)

    result = backfill_category_ids.backfill_products(
        [product],
        category_repository=FakeCategoryRepository(),
        categorizer=backfill_category_ids.RuleBasedCategorizer(),
        dry_run=False,
    )

    assert result.changed == 1
    assert product.category_id == 2


def test_backfill_main_forwards_filters_and_prints_summary(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_list_source_products(session: object, **kwargs: object) -> list[FakeProduct]:
        captured.update(kwargs)
        return [_product(title="Цемент М500", category_id=None)]

    monkeypatch.setattr(backfill_category_ids, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(backfill_category_ids, "_list_source_products", fake_list_source_products)
    monkeypatch.setattr(backfill_category_ids, "CategoryRepository", FakeCategoryRepository)
    monkeypatch.setattr(
        backfill_category_ids,
        "categorizer_for_session",
        lambda session: backfill_category_ids.RuleBasedCategorizer(),
    )

    result = backfill_category_ids.main(
        ["--source", "2gis", "--shop-id", "10", "--dry-run"]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert captured == {"source": "2gis", "shop_id": 10}
    assert (
        "category backfill summary: "
        "products_seen=1 "
        "changed=1 "
        "unchanged=0 "
        "unmatched=0 "
        "dry_run=True"
    ) in output


@dataclass
class FakeProduct:
    title: str
    category_id: int | None
    source: str = "2gis"
    category_raw: str | None = None
    description: str | None = None
    category_overrides: list["FakeOverride"] | None = None


@dataclass(frozen=True)
class FakeOverride:
    status: str


class LazyOverrideProduct:
    source = "2gis"
    category_raw = None
    description = None

    def __init__(self, *, title: str, category_id: int | None) -> None:
        self.title = title
        self.category_id = category_id

    @property
    def category_overrides(self) -> list[FakeOverride]:
        raise AssertionError("category_overrides should not be lazy-loaded")


@dataclass(frozen=True)
class FakeCategory:
    id: int


class FakeCategoryRepository:
    def __init__(self, session: object | None = None) -> None:
        self._session = session

    def upsert(self, data: object) -> FakeCategory:
        slug = data.slug
        ids = {
            "mixes_aggregates": 1,
            "cement": 2,
        }
        return FakeCategory(id=ids[slug])


class FakeSessionLocal:
    committed = False
    rolled_back = False

    def __enter__(self) -> "FakeSessionLocal":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _product(*, title: str, category_id: int | None) -> FakeProduct:
    return FakeProduct(title=title, category_id=category_id)
