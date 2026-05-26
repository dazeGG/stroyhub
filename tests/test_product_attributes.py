from decimal import Decimal

from stroyhub.catalog.attributes import extract_product_attributes, extract_title_attributes


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

    assert "dimension" in [attribute.kind for attribute in attributes]
    assert "thickness" in [attribute.kind for attribute in attributes]
    assert "length" not in [attribute.kind for attribute in attributes]


def test_extract_product_attributes_finds_osb_grade_and_thickness() -> None:
    extraction = extract_product_attributes("OSB-3 1,25х2,5м 9мм")

    assert extraction.confidence == Decimal("1.000")
    assert _attribute(extraction.attributes, "product_type").normalized == "osb"
    assert _attribute(extraction.attributes, "grade").normalized == "osb-3"
    assert _attribute(extraction.attributes, "dimension").values == (
        Decimal("1.25"),
        Decimal("2.5"),
    )
    thickness = _attribute(extraction.attributes, "thickness")
    assert thickness.values == (Decimal("9"),)
    assert thickness.unit == "mm"


def test_extract_product_attributes_finds_lumber_dimensions_length_and_material() -> None:
    extraction = extract_product_attributes("Брус 100*100мм L=6м сосна")

    assert _attribute(extraction.attributes, "product_type").normalized == "lumber"
    assert _attribute(extraction.attributes, "dimension").values == (
        Decimal("100"),
        Decimal("100"),
    )
    assert _attribute(extraction.attributes, "length").values == (Decimal("6"),)
    assert _attribute(extraction.attributes, "material").normalized == "pine"


def test_extract_product_attributes_finds_cement_grade_and_package_size() -> None:
    extraction = extract_product_attributes("Цемент М500 50кг")

    assert _attribute(extraction.attributes, "product_type").normalized == "cement"
    assert _attribute(extraction.attributes, "grade").normalized == "м500"
    assert _attribute(extraction.attributes, "weight").values == (Decimal("50"),)


def test_extract_product_attributes_finds_drywall_brand_model_and_thickness() -> None:
    extraction = extract_product_attributes("Гипсокартон ГСП-А KNAUF 2500мм*1200мм*9,5мм")

    assert _attribute(extraction.attributes, "product_type").normalized == "drywall"
    assert _attribute(extraction.attributes, "brand").normalized == "knauf"
    assert _attribute(extraction.attributes, "model").normalized == "gsp_a"
    assert _attribute(extraction.attributes, "thickness").values == (Decimal("9.5"),)


def test_extract_product_attributes_finds_profiled_sheet_grade_and_material() -> None:
    extraction = extract_product_attributes("Профлист С8 оцинкованный 0,45мм 1200х2000мм")

    assert _attribute(extraction.attributes, "product_type").normalized == "profiled_sheet"
    assert _attribute(extraction.attributes, "grade").normalized == "c8"
    assert _attribute(extraction.attributes, "material").normalized == "galvanized"
    assert _attribute(extraction.attributes, "thickness").values == (Decimal("0.45"),)
    assert _attribute(extraction.attributes, "dimension").values == (
        Decimal("1200"),
        Decimal("2000"),
    )


def test_extract_product_attributes_records_noise_reasons_and_lower_confidence() -> None:
    extraction = extract_product_attributes(
        "Гвозди цена указана за кг",
        source="2gis",
        category_raw="Крепеж",
    )

    assert extraction.confidence == Decimal("0.800")
    assert "source:2gis" in extraction.reasons
    assert "category_context_available" in extraction.reasons
    assert "noise:цена_указана" in extraction.reasons
    assert _attribute(extraction.attributes, "selling_unit").normalized == "kg"


def _attribute(attributes, kind: str):  # type: ignore[no-untyped-def]
    for attribute in attributes:
        if attribute.kind == kind:
            return attribute
    raise AssertionError(f"attribute {kind!r} not found in {attributes!r}")
