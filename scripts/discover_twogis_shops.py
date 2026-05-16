#!/usr/bin/env python
import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from stroyhub.scraping import scrape_twogis_branch


@dataclass(frozen=True, kw_only=True)
class CandidateShop:
    branch_id: str
    name: str
    address: str
    rubrics: str


CANDIDATE_SHOPS = [
    CandidateShop(
        branch_id="7037402698889811",
        name="Металл Торг",
        address="Проспект Михаила Николаева, 1",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="70000001007229923",
        name="Евролайн",
        address="Улица Курнатовского, 86",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="7037402698746785",
        name="Юником",
        address="Вилюйский тракт 3 километр, 1/4",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="7037402698836780",
        name="Пирамида",
        address="Переулок Космачёва, 2",
        rubrics="Стройматериалы",
    ),
    CandidateShop(
        branch_id="7037402698755240",
        name="Космос",
        address="Улица Космонавтов, 23",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="70000001038286835",
        name="ЛидерСтрой",
        address="Улица Жорницкого, 50а",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="70000001065271367",
        name="СибНорд",
        address="Улица Челюскина, 37/7в",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="7037402698774152",
        name="Ондулин",
        address="Улица Чернышевского, 48",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="7037402698745664",
        name="Интехстрой",
        address="Улица Леваневского, 3",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="70000001062470950",
        name="Востоктехторг",
        address="Проспект Михаила Николаева, 25/5",
        rubrics="Стройматериалы; доставка",
    ),
    CandidateShop(
        branch_id="70000001021201334",
        name="Строительный мир",
        address="Улица Чернышевского, 105",
        rubrics="Стройматериалы; доставка",
    ),
]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate candidate 2GIS Yakutsk construction-material shops."
    )
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--locale", default="ru_RU")
    args = parser.parse_args(argv)

    print(
        "\t".join(
            [
                "branch_id",
                "name",
                "address",
                "rubrics",
                "classification",
                "total",
                "pages_seen",
                "items_seen",
                "products_parsed",
                "priced_products",
                "completeness",
                "stop_reason",
            ]
        )
    )

    for candidate in CANDIDATE_SHOPS:
        try:
            result = scrape_twogis_branch(
                branch_id=candidate.branch_id,
                page_size=args.page_size,
                max_pages=args.max_pages,
                locale=args.locale,
            )
        except Exception as exc:
            print(
                "\t".join(
                    [
                        candidate.branch_id,
                        candidate.name,
                        candidate.address,
                        candidate.rubrics,
                        "failed",
                        "",
                        "",
                        "",
                        "",
                        "",
                        type(exc).__name__,
                        str(exc),
                    ]
                )
            )
            continue

        priced_products = sum(1 for product in result.products if product.price is not None)
        classification = "active" if priced_products > 0 else "no_prices"
        print(
            "\t".join(
                [
                    candidate.branch_id,
                    candidate.name,
                    candidate.address,
                    candidate.rubrics,
                    classification,
                    str(result.total),
                    str(result.pages_seen),
                    str(result.items_seen),
                    str(len(result.products)),
                    str(priced_products),
                    result.completeness,
                    result.stop_reason,
                ]
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
