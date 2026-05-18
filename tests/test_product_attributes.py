from decimal import Decimal

from stroyhub.catalog.attributes import extract_title_attributes


def test_extract_title_attributes_finds_weight_kg() -> None:
    attributes = extract_title_attributes("Цемент М500 50кг")

    assert _attribute(attributes, "weight").values == (Decimal("50"),)
    assert _attribute(attributes, "weight").unit == "kg"
    assert _attribute(attributes, "weight").raw == "50кг"


def test_extract_title_attributes_finds_volume_liters() -> None:
    attributes = extract_title_attributes("Грунтовка глубокого проникновения 10 л")

    assert _attribute(attributes, "volume").values == (Decimal("10"),)
    assert _attribute(attributes, "volume").unit == "l"
    assert _attribute(attributes, "volume").raw == "10 л"


def test_extract_title_attributes_finds_dimension_mm() -> None:
    attributes = extract_title_attributes("Гипсокартон KNAUF 2500мм*1200мм*9,5мм")

    dimension = _attribute(attributes, "dimension")
    assert dimension.values == (Decimal("2500"), Decimal("1200"), Decimal("9.5"))
    assert dimension.unit == "mm"
    assert dimension.raw == "2500мм*1200мм*9,5мм"


def test_extract_title_attributes_finds_length_meters() -> None:
    attributes = extract_title_attributes("Пленка полиэтиленовая ширина 1,50м")

    assert _attribute(attributes, "length").values == (Decimal("1.50"),)
    assert _attribute(attributes, "length").unit == "m"
    assert _attribute(attributes, "length").raw == "1,50м"


def test_extract_title_attributes_finds_area_m2() -> None:
    attributes = extract_title_attributes("Панель фасадная полезная площадь 0,39кв.м.")

    assert _attribute(attributes, "area").values == (Decimal("0.39"),)
    assert _attribute(attributes, "area").unit == "m2"
    assert _attribute(attributes, "area").raw == "0,39кв.м."


def test_extract_title_attributes_finds_package_count() -> None:
    attributes = extract_title_attributes("Сайдинг графит 238х3000мм (22шт. упак)")

    package_count = _attribute(attributes, "package_count")
    assert package_count.values == (Decimal("22"),)
    assert package_count.unit == "pcs"
    assert package_count.raw == "22шт. упак"


def test_extract_title_attributes_does_not_duplicate_dimension_parts_as_lengths() -> None:
    attributes = extract_title_attributes("Гипсокартон 2500мм*1200мм*9,5мм")

    assert [attribute.kind for attribute in attributes] == ["dimension"]


def _attribute(attributes, kind: str):  # type: ignore[no-untyped-def]
    for attribute in attributes:
        if attribute.kind == kind:
            return attribute
    raise AssertionError(f"attribute {kind!r} not found in {attributes!r}")
