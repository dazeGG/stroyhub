from collections.abc import Iterable

import pytest
from stroyhub.ml.category_queue import (
    CategoryLabelCandidate,
    CategoryLabelProduct,
    CategoryLabelQueueItem,
)
from stroyhub.ml.labels import CategoryLabelStore

from apps.ml.category_label_cli import LabelAction, parse_label_answer, run_label_session


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("1", LabelAction(kind="save", selected_category_ids=(10,))),
        ("1 3", LabelAction(kind="save", selected_category_ids=(10, 30))),
        ("1,3", LabelAction(kind="save", selected_category_ids=(10, 30))),
        ("n", LabelAction(kind="save", selected_category_ids=())),
        ("none", LabelAction(kind="save", selected_category_ids=())),
        ("s", LabelAction(kind="skip")),
        ("", LabelAction(kind="skip")),
        ("x", LabelAction(kind="not_product")),
        ("not_product", LabelAction(kind="not_product")),
    ],
)
def test_parse_label_answer_supported_flows(answer: str, expected: LabelAction) -> None:
    assert parse_label_answer(answer, (10, 20, 30)) == expected


def test_parse_label_answer_rejects_unknown_input() -> None:
    with pytest.raises(ValueError):
        parse_label_answer("wat", (10, 20, 30))


def test_run_label_session_saves_single_selection(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    queue = FakeQueue([_queue_item(product_id=1)])
    output = FakeOutput()

    result = run_label_session(
        queue,  # type: ignore[arg-type]
        label_store,
        limit=1,
        labeled_by="tester",
        input_fn=FakeInput(["2"]),
        output=output,
    )

    records = label_store.read_records()
    assert result.saved == 1
    assert result.skipped == 0
    assert records[0].product_id == 1
    assert records[0].candidate_category_ids == (10, 20, 30)
    assert records[0].selected_category_ids == (20,)
    assert records[0].labeled_by == "tester"
    assert "------------------------------------------------------------------------" in output.text


def test_run_label_session_saves_none_as_no_positive_target(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")

    result = run_label_session(
        FakeQueue([_queue_item(product_id=1)]),  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["n"]),
        output=FakeOutput(),
    )

    assert result.saved == 1
    assert label_store.read_records()[0].selected_category_ids == ()
    assert label_store.predictor_targets() == []
    assert [label.outcome for label in label_store.verifier_pair_labels()] == [
        "no_match",
        "no_match",
        "no_match",
    ]


def test_run_label_session_skips_current_item_and_continues(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    queue = FakeQueue([_queue_item(product_id=1), _queue_item(product_id=2)])

    result = run_label_session(
        queue,  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["s", "1"]),
        output=FakeOutput(),
    )

    records = label_store.read_records()
    assert result.saved == 1
    assert result.skipped == 1
    assert records[0].product_id == 2
    assert records[0].selected_category_ids == (10,)


def test_run_label_session_moves_to_next_product_after_save(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    queue = FakeQueue([_queue_item(product_id=1), _queue_item(product_id=2)])

    result = run_label_session(
        queue,  # type: ignore[arg-type]
        label_store,
        limit=2,
        input_fn=FakeInput(["1", "2"]),
        output=FakeOutput(),
    )

    records = label_store.read_records()
    assert result.saved == 2
    assert [record.product_id for record in records] == [1, 2]



def test_run_label_session_marks_not_product_and_continues(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    marked: list[int] = []
    queue = FakeQueue([_queue_item(product_id=1), _queue_item(product_id=2)])
    queue.mark_not_product = lambda pid: marked.append(pid)  # type: ignore[method-assign]

    result = run_label_session(
        queue,  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["x", "1"]),
        output=FakeOutput(),
    )

    assert result.not_product == 1
    assert result.saved == 1
    assert 1 in marked
    assert label_store.read_records()[0].product_id == 2


def test_run_label_session_shows_progress_counter(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    output = FakeOutput()

    run_label_session(
        FakeQueue([_queue_item(product_id=1)]),  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["1"]),
        output=output,
    )

    assert "labeled" in output.text
    assert "remaining" in output.text


def test_run_label_session_shows_shop_name(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    output = FakeOutput()

    run_label_session(
        FakeQueue([_queue_item(product_id=1, shop_name="Евролайн")]),  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["1"]),
        output=output,
    )

    assert "Евролайн" in output.text


def test_run_label_session_shows_session_stats_in_output(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    output = FakeOutput()

    run_label_session(
        FakeQueue([_queue_item(product_id=1)]),  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=FakeInput(["1"]),
        output=output,
    )

    assert "session" in output.text and "saved" in output.text


def test_run_label_session_recovers_from_undecodable_input(tmp_path) -> None:
    label_store = CategoryLabelStore(tmp_path / "labels.jsonl")
    output = FakeOutput()

    result = run_label_session(
        FakeQueue([_queue_item(product_id=1)]),  # type: ignore[arg-type]
        label_store,
        limit=1,
        input_fn=UndecodableThenValidInput("1"),
        output=output,
    )

    assert result.saved == 1
    assert label_store.read_records()[0].selected_category_ids == (10,)
    assert "Could not decode input" in output.text


class FakeQueue:
    def __init__(self, items: Iterable[CategoryLabelQueueItem]) -> None:
        self._items = tuple(items)

    def next_item(
        self,
        *,
        excluded_product_ids: set[int] | None = None,
    ) -> CategoryLabelQueueItem | None:
        excluded_product_ids = excluded_product_ids or set()
        for item in self._items:
            if item.product.id not in excluded_product_ids:
                return item
        return None

    def labeled_count(self) -> int:
        return 0

    def unlabeled_count(self) -> int:
        return len(self._items)

    def mark_not_product(self, product_id: int) -> None:
        pass


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


class UndecodableThenValidInput:
    def __init__(self, answer: str) -> None:
        self._answer = answer
        self._raised = False

    def __call__(self, _prompt: str) -> str:
        if not self._raised:
            self._raised = True
            raise UnicodeDecodeError("utf-8", b"\xd1", 0, 1, "invalid continuation byte")
        return self._answer


def _queue_item(*, product_id: int, shop_name: str | None = None) -> CategoryLabelQueueItem:
    return CategoryLabelQueueItem(
        product=CategoryLabelProduct(
            id=product_id,
            source="test",
            title=f"Product {product_id}",
            normalized_title=f"product {product_id}",
            category_id=None,
            category_raw=None,
            shop_name=shop_name,
        ),
        candidates=(
            CategoryLabelCandidate(
                id=10,
                slug="candidate-1",
                name="Candidate 1",
                parent_id=None,
                reason="fallback",
            ),
            CategoryLabelCandidate(
                id=20,
                slug="candidate-2",
                name="Candidate 2",
                parent_id=None,
                reason="fallback",
            ),
            CategoryLabelCandidate(
                id=30,
                slug="candidate-3",
                name="Candidate 3",
                parent_id=None,
                reason="fallback",
            ),
        ),
    )
