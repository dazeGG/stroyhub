from stroyhub.ml.features import (
    CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION,
    CategoryVerifierCategoryInput,
    CategoryVerifierProductInput,
    build_category_verifier_features,
)


def test_category_verifier_features_are_deterministic() -> None:
    product = CategoryVerifierProductInput(
        id=10,
        source="2gis",
        shop_id=5,
        title="  Цемент М500 25 кг ",
        normalized_title="цемент м500 25 кг",
        category_raw="Цемент",
        category_id=20,
        description="Сухая строительная смесь",
    )
    parent = CategoryVerifierCategoryInput(
        id=1,
        slug="mixes_aggregates",
        name="Смеси и сыпучие материалы",
    )
    category = CategoryVerifierCategoryInput(
        id=20,
        slug="cement",
        name="Цемент",
        parent_id=1,
    )

    first = build_category_verifier_features(
        product=product,
        category=category,
        category_path=(parent, category),
    )
    second = build_category_verifier_features(
        product=product,
        category=category,
        category_path=(parent, category),
    )

    assert first == second
    assert first.schema_version == CATEGORY_VERIFIER_FEATURE_SCHEMA_VERSION
    assert first.values == {
        "product.source": "2gis",
        "product.shop_id": "5",
        "product.title": "цемент м500 25 кг",
        "product.normalized_title": "цемент м500 25 кг",
        "product.category_raw": "цемент",
        "product.description": "сухая строительная смесь",
        "product.context_text": (
            "цемент м500 25 кг цемент м500 25 кг цемент "
            "сухая строительная смесь 2gis"
        ),
        "category.id": "20",
        "category.slug": "cement",
        "category.slug_text": "cement",
        "category.name": "цемент",
        "category.parent_id": "1",
        "category.path_names": "смеси и сыпучие материалы цемент",
        "category.path_slugs": "mixes aggregates cement",
        "category.context_text": (
            "цемент cement смеси и сыпучие материалы цемент mixes aggregates cement"
        ),
        "pair.context_text": (
            "цемент м500 25 кг цемент м500 25 кг цемент "
            "сухая строительная смесь 2gis цемент cement "
            "смеси и сыпучие материалы цемент mixes aggregates cement"
        ),
        "pair.product_has_current_category": "1",
        "pair.raw_category_mentions_category": "1",
        "pair.title_mentions_category": "1",
    }


def test_category_verifier_features_append_category_to_missing_path() -> None:
    product = CategoryVerifierProductInput(
        source="unicom",
        title="Клей плиточный",
    )
    parent = CategoryVerifierCategoryInput(
        id=1,
        slug="mixes_aggregates",
        name="Смеси и сыпучие материалы",
    )
    category = CategoryVerifierCategoryInput(
        id=30,
        slug="tile_adhesives",
        name="Плиточные клеи",
        parent_id=1,
    )

    row = build_category_verifier_features(
        product=product,
        category=category,
        category_path=(parent,),
    )

    assert row.values["category.path_names"] == "смеси и сыпучие материалы плиточные клеи"
    assert row.values["category.path_slugs"] == "mixes aggregates tile adhesives"
    assert row.values["product.shop_id"] == ""
    assert row.values["pair.product_has_current_category"] == "0"
