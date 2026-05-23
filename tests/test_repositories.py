from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    CanonicalProductCreate,
    CanonicalProductRepository,
    CategoryOverrideCreate,
    CategoryOverrideRepository,
    CategoryOverrideRevert,
    CategoryRepository,
    CategoryUpsert,
    PriceSnapshotCreate,
    PriceSnapshotRepository,
    ProductMatchCreate,
    ProductMatchRepository,
    ScrapeRunCreate,
    ScrapeRunRepository,
    ShopIdentityCreate,
    ShopIdentityRepository,
    ShopIdentityUpdate,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.models import (
    Category,
    CategoryOverride,
    PriceSnapshot,
    ProductMatch,
    ScrapeRun,
    Shop,
    ShopIdentity,
    SourceProduct,
)


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 1})

    try:
        connection = engine.connect()
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL is not available")

    transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_shop_repository_upserts_and_preserves_raw_payload(db_session: Session) -> None:
    repository = ShopRepository(db_session)

    shop = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-test-1",
            name="Initial Shop",
            address="Yakutsk",
            raw={"source": {"id": "branch-test-1"}},
        )
    )
    first_id = shop.id

    updated = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-test-1",
            name="Updated Shop",
            address="Yakutsk, Lenina 1",
            raw={"source": {"id": "branch-test-1", "updated": True}},
            scrape_status="success",
            error_count=2,
        )
    )

    count = db_session.scalar(
        select(func.count()).select_from(Shop).where(Shop.source_id == "branch-test-1")
    )

    assert updated.id == first_id
    assert updated.name == "Updated Shop"
    assert updated.address == "Yakutsk, Lenina 1"
    assert updated.raw == {"source": {"id": "branch-test-1", "updated": True}}
    assert updated.scrape_status == "success"
    assert updated.error_count == 2
    assert count == 1


def test_shop_repository_keeps_existing_optional_fields_when_upsert_omits_them(
    db_session: Session,
) -> None:
    repository = ShopRepository(db_session)
    shop = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-preserve-fields",
            name="Preserve Fields",
            address="Yakutsk, Address 1",
            url="https://shop.example.test/",
            raw={"candidate_id": 1},
        )
    )

    updated = repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="branch-preserve-fields",
            name="Preserve Fields",
            scrape_status="success",
        )
    )

    assert updated.id == shop.id
    assert updated.address == "Yakutsk, Address 1"
    assert updated.url == "https://shop.example.test/"
    assert updated.raw == {"candidate_id": 1}
    assert updated.scrape_status == "success"


def test_shop_identity_repository_links_source_specific_shops(
    db_session: Session,
) -> None:
    identity_repository = ShopIdentityRepository(db_session)
    shop_repository = ShopRepository(db_session)

    identity = identity_repository.create(
        ShopIdentityCreate(
            display_name="Юником",
            website_url="https://unicom-ykt.ru/",
            preferred_source="unicom",
            locked_fields={"display_name": True},
        )
    )
    twogis_shop = shop_repository.upsert(
        ShopUpsert(source="2gis", source_id="identity-2gis", name="Юником 2GIS")
    )
    official_shop = shop_repository.upsert(
        ShopUpsert(
            source="unicom",
            source_id="identity-official",
            name="Юником",
            shop_identity_id=identity.id,
        )
    )
    source_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=twogis_shop.id,
            source="2gis",
            source_product_id="identity-product",
            title="Identity product",
            normalized_title="identity product",
        )
    )

    linked_twogis_shop = identity_repository.link_shop(
        identity_id=identity.id,
        shop_id=twogis_shop.id,
    )
    source_shops = identity_repository.list_source_shops(identity.id)

    assert isinstance(identity, ShopIdentity)
    assert official_shop.source_type == "official_api"
    assert linked_twogis_shop.source_type == "2gis"
    assert linked_twogis_shop.shop_identity_id == identity.id
    assert {shop.source for shop in source_shops} == {"2gis", "unicom"}
    assert source_product.shop_id == twogis_shop.id


def test_shop_identity_update_respects_locked_fields(db_session: Session) -> None:
    repository = ShopIdentityRepository(db_session)
    identity = repository.create(
        ShopIdentityCreate(
            display_name="Admin maintained",
            address="Old address",
            locked_fields={"display_name": True},
        )
    )

    updated = repository.update(
        identity.id,
        ShopIdentityUpdate(
            display_name="2GIS refresh name",
            address="New address",
            preferred_source="2gis",
        ),
    )

    assert updated.display_name == "Admin maintained"
    assert updated.address == "New address"
    assert updated.preferred_source == "2gis"


def test_shop_identity_delete_detaches_sources_without_deleting_source_data(
    db_session: Session,
) -> None:
    identity_repository = ShopIdentityRepository(db_session)
    shop_repository = ShopRepository(db_session)
    identity = identity_repository.create(ShopIdentityCreate(display_name="Delete Me"))
    shop = shop_repository.upsert(
        ShopUpsert(
            source="2gis",
            source_id="delete-identity-source",
            name="Source",
            shop_identity_id=identity.id,
        )
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="delete-identity-product",
            title="Delete identity product",
            normalized_title="delete identity product",
        )
    )

    identity_repository.delete(identity.id)
    db_session.expire_all()

    assert db_session.get(ShopIdentity, identity.id) is None
    assert db_session.get(Shop, shop.id).shop_identity_id is None
    assert db_session.get(SourceProduct, product.id).shop_id == shop.id


def test_shop_repository_rejects_manual_source_type(db_session: Session) -> None:
    repository = ShopRepository(db_session)

    with pytest.raises(ValueError, match="unknown shop source type"):
        repository.upsert(
            ShopUpsert(
                source="manual",
                source_id="manual-shop",
                source_type="manual",
                name="Manual Shop",
            )
        )


def test_shop_identity_repository_rejects_manual_preferred_source(
    db_session: Session,
) -> None:
    repository = ShopIdentityRepository(db_session)

    with pytest.raises(ValueError, match="manual is not an accepted shop source"):
        repository.create(
            ShopIdentityCreate(
                display_name="Manual source",
                preferred_source="manual",
            )
        )


def test_source_product_repository_upserts_by_source_product_id(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-2", name="Shop")
    )
    repository = SourceProductRepository(db_session)
    observed_at = datetime(2026, 5, 16, 10, 0, tzinfo=UTC)

    product = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-1",
            title="Cement M500",
            normalized_title="cement m500",
            category_raw="Catalog / Cement",
            unit_raw="bag",
            raw={"id": "product-1", "price": "650"},
            observed_at=observed_at,
        )
    )
    first_id = product.id

    updated = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-1",
            title="Cement M500 50kg",
            normalized_title="cement m500 50kg",
            category_raw="Catalog / Cement",
            unit_raw="50 kg",
            raw={"id": "product-1", "price": "700"},
            observed_at=datetime(2026, 5, 16, 11, 0, tzinfo=UTC),
        )
    )

    count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )

    assert updated.id == first_id
    assert updated.title == "Cement M500 50kg"
    assert updated.unit_raw == "50 kg"
    assert updated.raw == {"id": "product-1", "price": "700"}
    assert updated.first_seen_at == observed_at
    assert count == 1


def test_category_repository_upserts_by_parent_and_slug(db_session: Session) -> None:
    repository = CategoryRepository(db_session)

    parent = repository.upsert(CategoryUpsert(slug="test-materials-parent", name="Materials"))
    category = repository.upsert(
        CategoryUpsert(slug="test-cement-child", name="Cement", parent_id=parent.id)
    )
    updated = repository.upsert(
        CategoryUpsert(slug="test-cement-child", name="Цемент", parent_id=parent.id)
    )

    count = db_session.scalar(
        select(func.count())
        .select_from(Category)
        .where(Category.slug.in_(["test-materials-parent", "test-cement-child"]))
    )

    assert updated.id == category.id
    assert updated.parent_id == parent.id
    assert updated.name == "Цемент"
    assert count == 2


def test_category_override_repository_creates_replaces_and_reverts(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="category-override-shop", name="Shop")
    )
    category_repository = CategoryRepository(db_session)
    original_category = category_repository.upsert(
        CategoryUpsert(slug="override-original", name="Original")
    )
    first_category = category_repository.upsert(
        CategoryUpsert(slug="override-first", name="First")
    )
    second_category = category_repository.upsert(
        CategoryUpsert(slug="override-second", name="Second")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="category-override-product",
            title="Override product",
            normalized_title="override product",
            category_id=original_category.id,
        )
    )

    repository = CategoryOverrideRepository(db_session)
    first_override = repository.create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product.id,
            category_id=first_category.id,
            reason="review",
            actor="admin",
        )
    )
    second_override = repository.create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product.id,
            category_id=second_category.id,
            actor="admin",
        )
    )

    active_override = repository.get_active(product.id)
    active_count = db_session.scalar(
        select(func.count())
        .select_from(CategoryOverride)
        .where(
            CategoryOverride.source_product_id == product.id,
            CategoryOverride.status == "active",
        )
    )

    assert first_override.status == "replaced"
    assert first_override.deactivated_by == "admin"
    assert second_override.previous_category_id == original_category.id
    assert active_override is not None
    assert active_override.id == second_override.id
    assert active_count == 1
    assert product.category_id == second_category.id

    reverted = repository.revert_active(
        CategoryOverrideRevert(source_product_id=product.id, actor="admin")
    )

    assert reverted is not None
    assert reverted.status == "reverted"
    assert repository.get_active(product.id) is None
    assert product.category_id == original_category.id


def test_category_override_repository_is_idempotent_for_same_active_payload(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="category-override-idempotent-shop", name="Shop")
    )
    category_repository = CategoryRepository(db_session)
    original_category = category_repository.upsert(
        CategoryUpsert(slug="override-idempotent-original", name="Original")
    )
    manual_category = category_repository.upsert(
        CategoryUpsert(slug="override-idempotent-manual", name="Manual")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="category-override-idempotent-product",
            title="Override product",
            normalized_title="override product",
            category_id=original_category.id,
        )
    )

    repository = CategoryOverrideRepository(db_session)
    first = repository.create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product.id,
            category_id=manual_category.id,
            reason="same reason",
            actor="admin",
        )
    )
    second = repository.create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product.id,
            category_id=manual_category.id,
            reason="  same reason  ",
            actor="  admin  ",
        )
    )
    all_rows = repository.list_for_product(product.id)

    assert second.id == first.id
    assert len(all_rows) == 1
    assert all_rows[0].status == "active"


def test_source_product_upsert_preserves_active_category_override(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="category-override-rescrape-shop", name="Shop")
    )
    category_repository = CategoryRepository(db_session)
    rule_category = category_repository.upsert(CategoryUpsert(slug="rule-category", name="Rule"))
    override_category = category_repository.upsert(
        CategoryUpsert(slug="manual-category", name="Manual")
    )
    product_repository = SourceProductRepository(db_session)
    product = product_repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="category-override-rescrape-product",
            title="Rescrape product",
            normalized_title="rescrape product",
            category_id=rule_category.id,
        )
    )
    CategoryOverrideRepository(db_session).create_or_replace(
        CategoryOverrideCreate(
            source_product_id=product.id,
            category_id=override_category.id,
            actor="admin",
        )
    )

    rescraped = product_repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="category-override-rescrape-product",
            title="Rescrape product updated",
            normalized_title="rescrape product updated",
            category_id=rule_category.id,
        )
    )

    assert rescraped.id == product.id
    assert rescraped.category_id == override_category.id


def test_source_product_repository_falls_back_to_fingerprint(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-3", name="Shop")
    )
    repository = SourceProductRepository(db_session)

    product = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            fingerprint="stable-fingerprint",
            title="Sand",
            normalized_title="sand",
            raw={"title": "Sand"},
        )
    )

    updated = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            fingerprint="stable-fingerprint",
            title="Sand washed",
            normalized_title="sand washed",
            raw={"title": "Sand washed"},
        )
    )

    assert updated.id == product.id
    assert updated.title == "Sand washed"
    assert updated.raw == {"title": "Sand washed"}


def test_source_product_repository_backfills_source_product_id_after_fingerprint_match(
    db_session: Session,
) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-4", name="Shop")
    )
    repository = SourceProductRepository(db_session)

    product = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            fingerprint="late-source-id-fingerprint",
            title="Concrete mix",
            normalized_title="concrete mix",
            raw={"title": "Concrete mix"},
        )
    )

    updated = repository.upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="late-source-product-id",
            fingerprint="late-source-id-fingerprint",
            title="Concrete mix M300",
            normalized_title="concrete mix m300",
            raw={"id": "late-source-product-id", "title": "Concrete mix M300"},
        )
    )

    count = db_session.scalar(
        select(func.count()).select_from(SourceProduct).where(SourceProduct.shop_id == shop.id)
    )

    assert updated.id == product.id
    assert updated.source_product_id == "late-source-product-id"
    assert updated.title == "Concrete mix M300"
    assert count == 1


def test_source_product_repository_requires_stable_identity(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-5", name="Shop")
    )

    with pytest.raises(ValueError, match="source_product_id or fingerprint"):
        SourceProductRepository(db_session).upsert(
            SourceProductUpsert(
                shop_id=shop.id,
                source="2gis",
                title="Unknown product",
                normalized_title="unknown product",
            )
        )


def test_price_snapshot_repository_is_append_only(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-6", name="Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id="product-2",
            title="Brick",
            normalized_title="brick",
        )
    )
    repository = PriceSnapshotRepository(db_session)

    first = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("10.50"),
            raw={"price": "10.50"},
        )
    )
    second = repository.add(
        PriceSnapshotCreate(
            source_product_id=product.id,
            price=Decimal("10.50"),
            raw={"price": "10.50"},
        )
    )

    count = db_session.scalar(
        select(func.count())
        .select_from(PriceSnapshot)
        .where(PriceSnapshot.source_product_id == product.id)
    )

    assert first.id != second.id
    assert first.raw == {"price": "10.50"}
    assert second.raw == {"price": "10.50"}
    assert count == 2


def test_scrape_run_repository_tracks_run_lifecycle(db_session: Session) -> None:
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source="2gis", source_id="branch-test-7", name="Shop")
    )
    repository = ScrapeRunRepository(db_session)
    started_at = datetime(2026, 5, 17, 9, 0, tzinfo=UTC)
    finished_at = datetime(2026, 5, 17, 9, 1, tzinfo=UTC)

    scrape_run = repository.start(
        ScrapeRunCreate(
            source="2gis",
            shop_id=shop.id,
            started_at=started_at,
            raw={"branch_id": "branch-test-7"},
        )
    )
    repository.finish(
        scrape_run,
        status="success",
        items_seen=3,
        items_saved=3,
        finished_at=finished_at,
        raw={"branch_id": "branch-test-7", "complete": True},
    )

    stored = db_session.get(ScrapeRun, scrape_run.id)

    assert stored is not None
    assert stored.status == "success"
    assert stored.items_seen == 3
    assert stored.items_saved == 3
    assert stored.started_at == started_at
    assert stored.finished_at == finished_at
    assert stored.raw == {"branch_id": "branch-test-7", "complete": True}


def test_canonical_product_repository_creates_and_lists_by_normalized_title(
    db_session: Session,
) -> None:
    category = CategoryRepository(db_session).upsert(
        CategoryUpsert(slug="test-match-cement", name="Cement")
    )
    repository = CanonicalProductRepository(db_session)

    product = repository.create(
        CanonicalProductCreate(
            category_id=category.id,
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
            brand="Test Brand",
            unit_raw="50кг",
            attributes={"weight": {"value": "50", "unit": "kg"}},
        )
    )

    matches = repository.list_by_normalized_title("цемент м500 50кг")

    assert product.id is not None
    assert product.category_id == category.id
    assert product.match_status == "active"
    assert product.attributes == {"weight": {"value": "50", "unit": "kg"}}
    assert matches == [product]


def test_product_match_repository_creates_lists_and_updates_status(
    db_session: Session,
) -> None:
    source_product = _source_product(db_session, source_id="match-product-1")
    canonical_product = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
        )
    )
    repository = ProductMatchRepository(db_session)
    matched_at = datetime(2026, 5, 18, 9, 0, tzinfo=UTC)

    match = repository.create(
        ProductMatchCreate(
            canonical_product_id=canonical_product.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.950"),
            method="exact_title",
            matched_at=matched_at,
            reason={"matched_normalized_title": "цемент м500 50кг"},
        )
    )

    listed = repository.list(status="candidate", source_product_id=source_product.id)
    reviewed_at = datetime(2026, 5, 18, 9, 5, tzinfo=UTC)
    updated = repository.update_status(
        match,
        status="accepted",
        reviewed_at=reviewed_at,
        reviewed_by="local_script",
    )

    assert listed == [match]
    assert updated.status == "accepted"
    assert updated.reviewed_at == reviewed_at
    assert updated.reviewed_by == "local_script"
    assert updated.reason == {"matched_normalized_title": "цемент м500 50кг"}


def test_product_match_repository_supports_rejected_and_superseded_statuses(
    db_session: Session,
) -> None:
    match = _product_match(db_session, status="candidate")
    repository = ProductMatchRepository(db_session)

    repository.update_status(match, status="rejected", reason={"review_note": "variant"})
    repository.update_status(match, status="superseded")

    assert match.status == "superseded"
    assert match.reason == {"review_note": "variant"}


def test_product_match_repository_rejects_unknown_status(db_session: Session) -> None:
    canonical_product = CanonicalProductRepository(db_session).create(
        CanonicalProductCreate(title="Цемент", normalized_title="цемент")
    )
    source_product = _source_product(db_session, source_id="match-product-unknown-status")

    with pytest.raises(ValueError, match="unknown product match status"):
        ProductMatchRepository(db_session).create(
            ProductMatchCreate(
                canonical_product_id=canonical_product.id,
                source_product_id=source_product.id,
                confidence=Decimal("0.900"),
                method="token_similarity",
                status="needs_review",
            )
        )


def test_product_match_repository_enforces_one_accepted_match_per_source_product(
    db_session: Session,
) -> None:
    source_product = _source_product(db_session, source_id="match-product-accepted")
    canonical_repository = CanonicalProductRepository(db_session)
    first_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Цемент М500", normalized_title="цемент м500")
    )
    second_canonical = canonical_repository.create(
        CanonicalProductCreate(title="Цемент М500 50кг", normalized_title="цемент м500 50кг")
    )
    repository = ProductMatchRepository(db_session)
    repository.create(
        ProductMatchCreate(
            canonical_product_id=first_canonical.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.990"),
            method="exact_title",
            status="accepted",
        )
    )

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            repository.create(
                ProductMatchCreate(
                    canonical_product_id=second_canonical.id,
                    source_product_id=source_product.id,
                    confidence=Decimal("0.980"),
                    method="manual",
                    status="accepted",
                )
            )


def _source_product(
    session: Session,
    *,
    source_id: str,
) -> SourceProduct:
    shop = ShopRepository(session).upsert(
        ShopUpsert(source="2gis", source_id=f"branch-{source_id}", name="Shop")
    )
    return SourceProductRepository(session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source="2gis",
            source_product_id=source_id,
            title="Цемент М500 50кг",
            normalized_title="цемент м500 50кг",
        )
    )


def _product_match(session: Session, *, status: str) -> ProductMatch:
    source_product = _source_product(session, source_id=f"match-product-{status}")
    canonical_product = CanonicalProductRepository(session).create(
        CanonicalProductCreate(title="Цемент М500 50кг", normalized_title="цемент м500 50кг")
    )
    return ProductMatchRepository(session).create(
        ProductMatchCreate(
            canonical_product_id=canonical_product.id,
            source_product_id=source_product.id,
            confidence=Decimal("0.850"),
            method="token_similarity",
            status=status,
        )
    )
