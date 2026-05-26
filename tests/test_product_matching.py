from dataclasses import dataclass

from stroyhub.ml.matching import generate_product_match_candidates
from stroyhub.parsers.common import normalize_title


@dataclass(frozen=True, kw_only=True)
class ProductRecord:
    id: int
    source: str = "test"
    shop_id: int
    title: str
    category_id: int | None = 1
    category_raw: str | None = "Сухие смеси"

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)


def test_generate_product_match_candidates_matches_exact_normalized_titles() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М500 50кг"),
            ProductRecord(id=2, shop_id=20, title="  цемент   м500 50кг "),
            ProductRecord(id=3, shop_id=30, title="Клей плиточный 25кг"),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.left.id == 1
    assert candidate.right.id == 2
    assert candidate.confidence == 1.0
    assert candidate.reason.method == "exact_normalized_title"
    assert candidate.reason.exact_title is True
    assert candidate.reason.matched_normalized_title == "цемент м500 50кг"
    assert candidate.reason.token_overlap == ("50кг", "м500", "цемент")


def test_generate_product_match_candidates_matches_near_titles_by_tokens() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Клей плиточный КНАУФ Флизен 25кг"),
            ProductRecord(id=2, shop_id=20, title="Клей КНАУФ Флизен плиточный 25 кг"),
            ProductRecord(id=3, shop_id=30, title="Пескобетон М300 30кг"),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.left.id == 1
    assert candidate.right.id == 2
    assert candidate.confidence == 1.0
    assert candidate.reason.method == "token_similarity"
    assert candidate.reason.exact_title is False
    assert candidate.reason.left_only_tokens == ()
    assert candidate.reason.right_only_tokens == ()


def test_generate_product_match_candidates_handles_stopwords_and_minor_variation() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Клей плиточный КНАУФ Флизен 25кг"),
            ProductRecord(id=2, shop_id=20, title="КНАУФ Флизен клей для плитки 25 кг"),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence == 1.0
    assert candidate.reason.method == "token_similarity"
    assert candidate.reason.token_overlap == ("25кг", "клей", "кнауф", "плиточный", "флизен")
    assert candidate.reason.left_only_tokens == ()
    assert candidate.reason.right_only_tokens == ()
    assert candidate.reason.ignored_tokens == ("для",)


def test_generate_product_match_candidates_returns_review_candidate_reason_metadata() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Штукатурка гипсовая Ротбанд KNAUF 30кг"),
            ProductRecord(id=2, shop_id=20, title="Штукатурка Ротбанд KNAUF 30кг белая"),
        ],
        min_confidence=0.66,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence == 0.667
    assert candidate.reason.method == "token_similarity"
    assert candidate.reason.token_overlap == ("30кг", "knauf", "ротбанд", "штукатурка")
    assert candidate.reason.left_only_tokens == ("гипсовая",)
    assert candidate.reason.right_only_tokens == ("белая",)


def test_generate_product_match_candidates_omits_low_confidence_pairs() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М500 50кг"),
            ProductRecord(id=2, shop_id=20, title="Гипсокартон KNAUF 2500мм*1200мм*9,5мм"),
        ]
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_categories() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М500 50кг", category_id=1),
            ProductRecord(id=2, shop_id=20, title="Цемент М500 50кг", category_id=2),
        ]
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_weights() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М500 50кг"),
            ProductRecord(id=2, shop_id=20, title="Цемент М500 25кг"),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_package_counts() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Сайдинг графит 238х3000мм 22шт. упак"),
            ProductRecord(id=2, shop_id=20, title="Сайдинг графит 238х3000мм 10шт. упак"),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_dimensions() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Гипсокартон KNAUF 2500мм*1200мм*9,5мм"),
            ProductRecord(id=2, shop_id=20, title="Гипсокартон KNAUF 2500мм*1200мм*12,5мм"),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_separate_thickness() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="OSB-3 1,25х2,5м 9мм"),
            ProductRecord(id=2, shop_id=20, title="OSB-3 1,25х2,5м 12мм"),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_grades() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М400 50кг"),
            ProductRecord(id=2, shop_id=20, title="Цемент М500 50кг"),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_blocks_different_finish_colors() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(
                id=1,
                shop_id=10,
                title="Сайдинг графит 238х3000мм",
                category_raw="Сайдинг, фасадные панели",
            ),
            ProductRecord(
                id=2,
                shop_id=20,
                title="Сайдинг белый 238х3000мм",
                category_raw="Сайдинг, фасадные панели",
            ),
        ],
        min_confidence=0,
    )

    assert candidates == ()


def test_generate_product_match_candidates_can_allow_exact_category_mismatch() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Цемент М500 50кг", category_id=1),
            ProductRecord(id=2, shop_id=20, title="Цемент М500 50кг", category_id=2),
        ],
        allow_category_mismatch=True,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence == 0.9
    assert candidate.reason.method == "exact_normalized_title"
    assert candidate.reason.same_category is False


def test_generate_product_match_candidates_matches_exact_title_within_same_shop() -> None:
    candidates = generate_product_match_candidates(
        [
            ProductRecord(id=1, shop_id=10, title="Пескобетон М300 30кг"),
            ProductRecord(id=2, shop_id=10, title=" пескобетон  м300 30кг "),
        ]
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.left.shop_id == candidate.right.shop_id
    assert candidate.confidence == 1.0
    assert candidate.reason.matched_normalized_title == "пескобетон м300 30кг"
