from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from stroyhub.ml.not_product_labels import (
    NotProductLabel,
    NotProductLabelRecord,
    NotProductLabelStore,
)

DEFAULT_REVIEW_PATH = Path(".var/ml/patron/review.jsonl")

LabelActionKind = Literal["save", "skip", "undo", "quit"]

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"


class Writer(Protocol):
    def write(self, text: str) -> object:
        pass


@dataclass(frozen=True, kw_only=True)
class NotProductReviewItem:
    source_product_id: int
    title: str
    source: str | None = None
    shop_name: str | None = None
    category_raw: str | None = None
    normalized_category: str | None = None
    latest_price: str | None = None
    latest_currency: str | None = None
    unit_raw: str | None = None
    price_text: str | None = None
    gpt_label: str | None = None
    gpt_confidence: str | None = None
    gpt_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class LabelAction:
    kind: LabelActionKind
    label: NotProductLabel | None = None


@dataclass(frozen=True, kw_only=True)
class LabelSessionResult:
    saved: int
    skipped: int
    exhausted: bool
    quit_requested: bool = False


@dataclass(frozen=True, kw_only=True)
class _UndoEntry:
    kind: Literal["save", "skip"]
    product_id: int


class NotProductReviewQueue:
    def __init__(
        self,
        items: Iterable[NotProductReviewItem],
        label_store: NotProductLabelStore,
    ) -> None:
        self._items = tuple(items)
        self._label_store = label_store

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        label_store: NotProductLabelStore,
    ) -> NotProductReviewQueue:
        return cls(_read_review_items(Path(path)), label_store)

    def next_item(
        self,
        *,
        excluded_product_ids: set[int] | None = None,
    ) -> NotProductReviewItem | None:
        excluded_product_ids = excluded_product_ids or set()
        labeled_ids = self._label_store.labeled_product_ids()
        for item in self._items:
            if item.source_product_id in excluded_product_ids:
                continue
            if item.source_product_id in labeled_ids:
                continue
            return item
        return None

    def total_count(self) -> int:
        return len(self._items)

    def labeled_count(self) -> int:
        labeled_ids = self._label_store.labeled_product_ids()
        return sum(1 for item in self._items if item.source_product_id in labeled_ids)

    def remaining_count(self, *, excluded_product_ids: set[int] | None = None) -> int:
        excluded_product_ids = excluded_product_ids or set()
        labeled_ids = self._label_store.labeled_product_ids()
        return sum(
            1
            for item in self._items
            if item.source_product_id not in labeled_ids
            and item.source_product_id not in excluded_product_ids
        )


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdin()
    parser = argparse.ArgumentParser(
        description="Manually label Patron-uncertain product suitability decisions."
    )
    parser.add_argument("--review-path", default=str(DEFAULT_REVIEW_PATH))
    parser.add_argument("--labels-path", type=str)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--labeled-by", default="cli")
    args = parser.parse_args(argv)

    label_store = (
        NotProductLabelStore.default()
        if args.labels_path is None
        else NotProductLabelStore.from_path(args.labels_path)
    )
    queue = NotProductReviewQueue.from_jsonl(args.review_path, label_store)
    result = run_label_session(
        queue,
        label_store,
        limit=args.limit,
        labeled_by=args.labeled_by,
    )

    print(
        "not-product labeling summary: "
        f"saved={result.saved} "
        f"skipped={result.skipped} "
        f"exhausted={result.exhausted} "
        f"quit_requested={result.quit_requested} "
        f"labels_path={label_store.path}"
    )
    return 0


def run_label_session(
    queue: NotProductReviewQueue,
    label_store: NotProductLabelStore,
    *,
    limit: int | None = None,
    labeled_by: str | None = "cli",
    input_fn: Callable[[str], str] = input,
    output: Writer | None = None,
) -> LabelSessionResult:
    saved = 0
    skipped = 0
    excluded_product_ids: set[int] = set()
    undo_stack: list[_UndoEntry] = []
    output = output or _Stdout()

    while limit is None or saved < limit:
        item = queue.next_item(excluded_product_ids=excluded_product_ids)
        if item is None:
            return LabelSessionResult(saved=saved, skipped=skipped, exhausted=True)

        _print_item(item, queue, output, saved=saved, skipped=skipped)
        try:
            action = _read_action(input_fn=input_fn, output=output)
        except KeyboardInterrupt:
            output.write("\n")
            return LabelSessionResult(
                saved=saved,
                skipped=skipped,
                exhausted=False,
                quit_requested=True,
            )

        if action.kind == "quit":
            return LabelSessionResult(
                saved=saved,
                skipped=skipped,
                exhausted=False,
                quit_requested=True,
            )
        if action.kind == "undo":
            if not undo_stack:
                output.write("Nothing to undo.\n")
                continue
            entry = undo_stack.pop()
            excluded_product_ids.discard(entry.product_id)
            if entry.kind == "save":
                label_store.pop_last()
                saved -= 1
            elif entry.kind == "skip":
                skipped -= 1
            continue
        if action.kind == "skip":
            excluded_product_ids.add(item.source_product_id)
            skipped += 1
            undo_stack.append(_UndoEntry(kind="skip", product_id=item.source_product_id))
            continue

        if action.label is None:
            raise RuntimeError("save action must include a label")

        label_store.append(
            NotProductLabelRecord(
                source_product_id=item.source_product_id,
                label=action.label,
                labeled_by=labeled_by,
            )
        )
        excluded_product_ids.add(item.source_product_id)
        saved += 1
        undo_stack.append(_UndoEntry(kind="save", product_id=item.source_product_id))

    return LabelSessionResult(saved=saved, skipped=skipped, exhausted=False)


def parse_label_answer(answer: str) -> LabelAction:
    normalized = answer.strip().lower()
    if normalized in {"1", "p", "product", "т", "товар"}:
        return LabelAction(kind="save", label="product")
    if normalized in {"2", "n", "not_product", "not-product", "н", "не товар"}:
        return LabelAction(kind="save", label="not_product")
    if normalized in {"s", "skip", "", "ы", "с"}:
        return LabelAction(kind="skip")
    if normalized in {"u", "undo", "г", "у"}:
        return LabelAction(kind="undo")
    if normalized in {"q", "quit", "й", "выйти"}:
        return LabelAction(kind="quit")
    raise ValueError("Use 1=product, 2=not product, s=skip, u=undo, q=quit.")


def _read_action(
    *,
    input_fn: Callable[[str], str],
    output: Writer,
) -> LabelAction:
    prompt = "1=Товар, 2=Не товар, s=skip, u=undo, q=quit: "
    while True:
        try:
            answer = input_fn(prompt)
        except UnicodeDecodeError:
            output.write("Could not decode input. Use 1, 2, s, u, or q.\n")
            continue
        try:
            return parse_label_answer(answer)
        except ValueError as error:
            output.write(f"{error}\n")


def _print_item(
    item: NotProductReviewItem,
    queue: NotProductReviewQueue,
    output: Writer,
    *,
    saved: int,
    skipped: int,
) -> None:
    clicked = queue.labeled_count()
    remaining = queue.remaining_count()
    output.write("\n")
    output.write(_c(_DIM, "-" * 72) + "\n")
    output.write(
        _c(
            _DIM,
            f"[clicked: {clicked} / remaining: {remaining} / total: {queue.total_count()}]",
        )
        + "\n"
    )
    output.write(_c(_DIM, f"[session: {saved} saved, {skipped} skipped]") + "\n")
    output.write("\n")
    output.write(_c(_BOLD, f"Product #{item.source_product_id}: {item.title}") + "\n")
    if item.source:
        output.write(f"Source: {_c(_CYAN, item.source)}")
        if item.shop_name:
            output.write(f"  Shop: {_c(_CYAN, item.shop_name)}")
        output.write("\n")
    if item.category_raw:
        output.write(f"Raw category: {_c(_YELLOW, item.category_raw)}\n")
    if item.normalized_category:
        output.write(f"Category: {_c(_YELLOW, item.normalized_category)}\n")
    price_display = _price_display(item)
    if price_display:
        output.write(f"Price: {_c(_GREEN, price_display)}\n")
    if item.gpt_label:
        confidence = f", confidence={item.gpt_confidence}" if item.gpt_confidence else ""
        output.write(f"GPT: {_c(_GREEN, item.gpt_label)}{confidence}\n")
    if item.gpt_reasons:
        output.write("GPT reasons:\n")
        for reason in item.gpt_reasons:
            output.write(f"  - {reason}\n")
    output.write("\n")
    output.write("1. Товар\n")
    output.write("2. Не товар\n")
    output.write("\n")


def _read_review_items(path: Path) -> tuple[NotProductReviewItem, ...]:
    if not path.exists():
        raise FileNotFoundError(f"review queue not found: {path}")

    items: list[NotProductReviewItem] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL record at {path}:{line_number}") from error
            items.append(_review_item_from_json(payload))
    return tuple(items)


def _review_item_from_json(payload: object) -> NotProductReviewItem:
    if not isinstance(payload, dict):
        raise ValueError("review item must be a JSON object")

    source_product_id = _first_int(
        payload,
        "source_product_id",
        "product_id",
        "id",
    )
    if source_product_id is None or source_product_id <= 0:
        raise ValueError("review item must include positive source_product_id")

    title = _first_str(payload, "title", "product_title")
    if not title:
        raise ValueError("review item must include title")

    return NotProductReviewItem(
        source_product_id=source_product_id,
        title=title,
        source=_first_str(payload, "source"),
        shop_name=_first_str(payload, "shop_name", "shop"),
        category_raw=_first_str(payload, "category_raw", "raw_category"),
        normalized_category=_normalized_category(payload),
        latest_price=_first_str(payload, "latest_price", "price"),
        latest_currency=_first_str(payload, "latest_currency", "currency"),
        unit_raw=_first_str(payload, "unit_raw"),
        price_text=_first_str(
            payload,
            "price_text",
            "price_label",
            "price_display",
            "raw_price",
        ),
        gpt_label=_first_str(payload, "gpt_label", "predicted_label", "label"),
        gpt_confidence=_first_str(payload, "gpt_confidence", "confidence"),
        gpt_reasons=_string_tuple(payload.get("gpt_reasons") or payload.get("reasons")),
    )


def _first_int(payload: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _first_str(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalized_category(payload: dict[str, object]) -> str | None:
    category_path = payload.get("category_path")
    if isinstance(category_path, list):
        parts = [str(part).strip() for part in category_path if str(part).strip()]
        if parts:
            return " / ".join(parts)
    return _first_str(payload, "category_name", "normalized_category")


def _price_display(item: NotProductReviewItem) -> str | None:
    if item.price_text:
        return item.price_text
    if item.latest_price is None:
        return None

    parts = [item.latest_price]
    if item.latest_currency:
        parts.append(item.latest_currency)
    if item.unit_raw:
        parts.append(f"/ {item.unit_raw}")
    return " ".join(parts)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _configure_stdin() -> None:
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def _c(colour: str, text: str) -> str:
    return f"{colour}{text}{_RESET}"


class _Stdout:
    def write(self, text: str) -> object:
        return sys.stdout.write(text)


if __name__ == "__main__":
    raise SystemExit(main())
