from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from stroyhub.core.config import settings
from stroyhub.db import (
    CategoryRepository,
    CategoryUpsert,
    ShopRepository,
    ShopUpsert,
    SourceProductRepository,
    SourceProductUpsert,
)
from stroyhub.ml.category_queue import CategoryLabelQueue
from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore


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


def test_category_label_queue_prefers_current_category_signal(
    db_session: Session,
    tmp_path,
) -> None:
    categories = _seed_categories(db_session, prefix="queue-current")
    source = "queue-current-source"
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source=source, source_id="queue-current-shop", name="Queue Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-current-product",
            title="Цемент М500",
            normalized_title="цемент м500",
            category_id=categories["cement"],
            category_raw="Цемент",
            observed_at=datetime(2026, 5, 22, 1, 0, tzinfo=UTC),
        )
    )

    item = CategoryLabelQueue(
        db_session,
        CategoryLabelStore(tmp_path / "labels.jsonl"),
        source=source,
    ).next_item()

    assert item is not None
    assert item.product.id == product.id
    assert len(item.candidates) == 3
    assert item.candidates[0].id == categories["cement"]
    assert item.candidates[0].reason == "current_category"


def test_category_label_queue_uses_text_signal_without_current_category(
    db_session: Session,
    tmp_path,
) -> None:
    categories = _seed_categories(db_session, prefix="queue-text")
    source = "queue-text-source"
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source=source, source_id="queue-text-shop", name="Queue Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-text-product",
            title="Очередная категория товар",
            normalized_title="очередная категория товар",
            category_raw="Очередная категория",
        )
    )

    item = CategoryLabelQueue(
        db_session,
        CategoryLabelStore(tmp_path / "labels.jsonl"),
        source=source,
    ).next_item()

    assert item is not None
    assert item.product.id == product.id
    assert item.candidates[0].id == categories["custom"]
    assert item.candidates[0].reason == "text_signal"


def test_category_label_queue_excludes_already_labeled_products(
    db_session: Session,
    tmp_path,
) -> None:
    categories = _seed_categories(db_session, prefix="queue-skip")
    source = "queue-skip-source"
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source=source, source_id="queue-skip-shop", name="Queue Shop")
    )
    product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-skip-product",
            title="Цемент М500",
            normalized_title="цемент м500",
            category_id=categories["cement"],
            category_raw="Цемент",
        )
    )
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    label_store.append(
        CategoryLabelRecord(
            product_id=product.id,
            candidate_category_ids=tuple(categories.values()),
            selected_category_ids=(categories["cement"],),
        )
    )

    item = CategoryLabelQueue(db_session, label_store, source=source).next_item()

    assert item is None


def test_category_label_queue_only_excludes_labeled_products(
    db_session: Session,
    tmp_path,
) -> None:
    categories = _seed_categories(db_session, prefix="queue-partial")
    source = "queue-partial-source"
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source=source, source_id="queue-partial-shop", name="Queue Shop")
    )
    labeled_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-partial-labeled",
            title="Цемент М500",
            normalized_title="цемент м500",
            category_id=categories["cement"],
            category_raw="Цемент",
        )
    )
    unlabeled_product = SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-partial-unlabeled",
            title="Кирпич красный",
            normalized_title="кирпич красный",
            category_id=categories["brick"],
            category_raw="Кирпич",
        )
    )
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    label_store.append(
        CategoryLabelRecord(
            product_id=labeled_product.id,
            candidate_category_ids=tuple(categories.values()),
            selected_category_ids=(categories["cement"],),
        )
    )

    item = CategoryLabelQueue(db_session, label_store, source=source).next_item()

    assert item is not None
    assert item.product.id == unlabeled_product.id


def test_category_label_queue_shuffle_returns_product(
    db_session: Session,
    tmp_path,
) -> None:
    categories = _seed_categories(db_session, prefix="queue-shuffle")
    source = "queue-shuffle-source"
    shop = ShopRepository(db_session).upsert(
        ShopUpsert(source=source, source_id="queue-shuffle-shop", name="Queue Shop")
    )
    SourceProductRepository(db_session).upsert(
        SourceProductUpsert(
            shop_id=shop.id,
            source=source,
            source_product_id="queue-shuffle-product",
            title="Цемент М500",
            normalized_title="цемент м500",
            category_id=categories["cement"],
            category_raw="Цемент",
        )
    )

    item = CategoryLabelQueue(
        db_session,
        CategoryLabelStore(tmp_path / "labels.jsonl"),
        source=source,
        shuffle=True,
    ).next_item()

    assert item is not None
    assert len(item.candidates) == 3


def _seed_categories(db_session: Session, *, prefix: str) -> dict[str, int]:
    repository = CategoryRepository(db_session)
    root = repository.upsert(CategoryUpsert(slug=f"{prefix}-root", name=f"{prefix} root"))
    cement = repository.upsert(
        CategoryUpsert(slug=f"{prefix}-cement", name="Цемент", parent_id=root.id)
    )
    brick = repository.upsert(
        CategoryUpsert(slug=f"{prefix}-brick", name="Кирпич", parent_id=root.id)
    )
    paint = repository.upsert(
        CategoryUpsert(slug=f"{prefix}-paint", name="Краска", parent_id=root.id)
    )
    plaster = repository.upsert(
        CategoryUpsert(slug=f"{prefix}-plaster", name="Штукатурка", parent_id=root.id)
    )
    custom = repository.upsert(
        CategoryUpsert(
            slug=f"{prefix}-custom",
            name="Очередная категория",
            parent_id=root.id,
        )
    )
    return {
        "cement": cement.id,
        "brick": brick.id,
        "paint": paint.id,
        "plaster": plaster.id,
        "custom": custom.id,
    }
