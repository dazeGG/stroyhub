from collections.abc import Iterable

import pytest
from stroyhub.ml.not_product_labels import NotProductLabelRecord, NotProductLabelStore

from apps.ml.patron.label_cli import (
    LabelAction,
    NotProductReviewItem,
    NotProductReviewQueue,
    parse_label_answer,
    run_label_session,
)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1", LabelAction(kind="save", label="product")),
        ("товар", LabelAction(kind="save", label="product")),
        ("2", LabelAction(kind="save", label="not_product")),
        ("не товар", LabelAction(kind="save", label="not_product")),
        ("s", LabelAction(kind="skip")),
        ("", LabelAction(kind="skip")),
        ("u", LabelAction(kind="undo")),
        ("q", LabelAction(kind="quit")),
    ],
)
def test_parse_label_answer_supported_flows(answer: str, expected: LabelAction) -> None:
    assert parse_label_answer(answer) == expected


def test_parse_label_answer_rejects_unknown_input() -> None:
    with pytest.raises(ValueError):
        parse_label_answer("wat")


def test_run_label_session_saves_product_label(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    output = FakeOutput()

    result = run_label_session(
        _queue([_item(product_id=1)], label_store),
        label_store,
        limit=1,
        labeled_by="tester",
        input_fn=FakeInput(["1"]),
        output=output,
    )

    records = label_store.read_records()
    assert result.saved == 1
    assert records[0].source_product_id == 1
    assert records[0].label == "product"
    assert records[0].labeled_by == "tester"
    assert "clicked" in output.text and "remaining" in output.text
    assert "1. Товар" in output.text
    assert "2. Не товар" in output.text


def test_run_label_session_saves_not_product_label(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    run_label_session(
        _queue([_item(product_id=1)], label_store),
        label_store,
        limit=1,
        input_fn=FakeInput(["2"]),
        output=FakeOutput(),
    )

    assert label_store.read_records()[0].label == "not_product"


def test_queue_skips_already_labeled_items(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    label_store.append(NotProductLabelRecord(source_product_id=1, label="product"))
    queue = _queue([_item(product_id=1), _item(product_id=2)], label_store)

    assert queue.labeled_count() == 1
    assert queue.remaining_count() == 1
    assert queue.next_item().source_product_id == 2


def test_run_label_session_skips_current_item_and_continues(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    result = run_label_session(
        _queue([_item(product_id=1), _item(product_id=2)], label_store),
        label_store,
        limit=1,
        input_fn=FakeInput(["s", "2"]),
        output=FakeOutput(),
    )

    records = label_store.read_records()
    assert result.saved == 1
    assert result.skipped == 1
    assert records[0].source_product_id == 2
    assert records[0].label == "not_product"


def test_run_label_session_undo_save(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    result = run_label_session(
        _queue([_item(product_id=1), _item(product_id=2)], label_store),
        label_store,
        limit=2,
        input_fn=FakeInput(["1", "u", "2", "1"]),
        output=FakeOutput(),
    )

    records = label_store.read_records()
    assert result.saved == 2
    assert records[0].source_product_id == 1
    assert records[0].label == "not_product"
    assert records[1].source_product_id == 2
    assert records[1].label == "product"


def test_run_label_session_undo_skip(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    result = run_label_session(
        _queue([_item(product_id=1), _item(product_id=2)], label_store),
        label_store,
        limit=1,
        input_fn=FakeInput(["s", "u", "1"]),
        output=FakeOutput(),
    )

    assert result.saved == 1
    assert result.skipped == 0
    assert label_store.read_records()[0].source_product_id == 1


def test_run_label_session_quit_returns_without_saving(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    result = run_label_session(
        _queue([_item(product_id=1)], label_store),
        label_store,
        input_fn=FakeInput(["q"]),
        output=FakeOutput(),
    )

    assert result.quit_requested is True
    assert result.saved == 0
    assert label_store.read_records() == []


def test_review_queue_reads_gpt_generated_jsonl(tmp_path) -> None:
    review_path = tmp_path / "review.jsonl"
    review_path.write_text(
        (
            '{"source_product_id": 10, "title": "Фонарь", "source": "unicom", '
            '"shop_name": "Юником", "category_raw": "Фонари", '
            '"price_text": "от 1500 RUB", "latest_price": "1500.00", '
            '"latest_currency": "RUB", "unit_raw": "шт", '
            '"gpt_label": "not_product", "gpt_confidence": "0.64", '
            '"gpt_reasons": ["not construction material"]}\n'
        ),
        encoding="utf-8",
    )
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")

    queue = NotProductReviewQueue.from_jsonl(review_path, label_store)
    item = queue.next_item()

    assert item is not None
    assert item.source_product_id == 10
    assert item.price_text == "от 1500 RUB"
    assert item.latest_price == "1500.00"
    assert item.latest_currency == "RUB"
    assert item.unit_raw == "шт"
    assert item.gpt_label == "not_product"
    assert item.gpt_reasons == ("not construction material",)


def test_run_label_session_prints_price_text(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    output = FakeOutput()

    run_label_session(
        _queue([_item(product_id=1, price_text="от 1500 RUB")], label_store),
        label_store,
        input_fn=FakeInput(["q"]),
        output=output,
    )

    assert "Price:" in output.text
    assert "от 1500 RUB" in output.text


def test_run_label_session_prints_latest_price_when_price_text_is_missing(tmp_path) -> None:
    label_store = NotProductLabelStore(tmp_path / "human_labels.jsonl")
    output = FakeOutput()

    run_label_session(
        _queue(
            [
                _item(
                    product_id=1,
                    latest_price="2500.00",
                    latest_currency="RUB",
                    unit_raw="м3",
                )
            ],
            label_store,
        ),
        label_store,
        input_fn=FakeInput(["q"]),
        output=output,
    )

    assert "Price:" in output.text
    assert "2500.00 RUB / м3" in output.text


class FakeInput:
    def __init__(self, answers: Iterable[str]) -> None:
        self._answers = iter(answers)

    def __call__(self, _prompt: str) -> str:
        return next(self._answers)


class FakeOutput:
    def __init__(self) -> None:
        self.text = ""

    def write(self, text: str) -> object:
        self.text += text
        return len(text)


def _queue(
    items: Iterable[NotProductReviewItem],
    label_store: NotProductLabelStore,
) -> NotProductReviewQueue:
    return NotProductReviewQueue(items, label_store)


def _item(
    *,
    product_id: int,
    latest_price: str | None = None,
    latest_currency: str | None = None,
    unit_raw: str | None = None,
    price_text: str | None = None,
) -> NotProductReviewItem:
    return NotProductReviewItem(
        source_product_id=product_id,
        source="test",
        shop_name="Test shop",
        title=f"Product {product_id}",
        category_raw="Raw category",
        latest_price=latest_price,
        latest_currency=latest_currency,
        unit_raw=unit_raw,
        price_text=price_text,
    )
