from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from stroyhub.db import SessionLocal
from stroyhub.ml.category_queue import CategoryLabelQueue, CategoryLabelQueueItem
from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore

LabelActionKind = Literal["save", "skip", "quit"]


class Writer(Protocol):
    def write(self, text: str) -> object:
        pass


@dataclass(frozen=True, kw_only=True)
class LabelAction:
    kind: LabelActionKind
    selected_category_ids: tuple[int, ...] = ()


@dataclass(frozen=True, kw_only=True)
class LabelSessionResult:
    saved: int
    skipped: int
    quit_requested: bool
    exhausted: bool


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Label product/category matches for the category verifier dataset."
    )
    parser.add_argument("--labels-path", type=str)
    parser.add_argument("--source")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--labeled-by", default="cli")
    args = parser.parse_args(argv)

    label_store = (
        CategoryLabelStore.default()
        if args.labels_path is None
        else CategoryLabelStore.from_path(args.labels_path)
    )

    with SessionLocal() as session:
        result = run_label_session(
            CategoryLabelQueue(session, label_store, source=args.source),
            label_store,
            limit=args.limit,
            labeled_by=args.labeled_by,
        )

    print(
        "labeling summary: "
        f"saved={result.saved} "
        f"skipped={result.skipped} "
        f"quit={result.quit_requested} "
        f"exhausted={result.exhausted} "
        f"labels_path={label_store.path}"
    )
    return 0


def run_label_session(
    queue: CategoryLabelQueue,
    label_store: CategoryLabelStore,
    *,
    limit: int | None = None,
    labeled_by: str | None = "cli",
    input_fn: Callable[[str], str] = input,
    output: Writer | None = None,
) -> LabelSessionResult:
    saved = 0
    skipped = 0
    excluded_product_ids: set[int] = set()
    output = output or _Stdout()

    while limit is None or saved < limit:
        item = queue.next_item(excluded_product_ids=excluded_product_ids)
        if item is None:
            return LabelSessionResult(
                saved=saved,
                skipped=skipped,
                quit_requested=False,
                exhausted=True,
            )

        _print_item(item, output)
        action = _read_action(item, input_fn=input_fn, output=output)
        if action.kind == "quit":
            return LabelSessionResult(
                saved=saved,
                skipped=skipped,
                quit_requested=True,
                exhausted=False,
            )
        if action.kind == "skip":
            excluded_product_ids.add(item.product.id)
            skipped += 1
            continue

        label_store.append(
            CategoryLabelRecord(
                product_id=item.product.id,
                candidate_category_ids=tuple(candidate.id for candidate in item.candidates),
                selected_category_ids=action.selected_category_ids,
                labeled_by=labeled_by,
            )
        )
        excluded_product_ids.add(item.product.id)
        saved += 1

    return LabelSessionResult(
        saved=saved,
        skipped=skipped,
        quit_requested=False,
        exhausted=False,
    )


def parse_label_answer(answer: str, candidate_category_ids: tuple[int, ...]) -> LabelAction:
    normalized = answer.strip().lower()
    if normalized in {"q", "quit", "exit"}:
        return LabelAction(kind="quit")
    if normalized in {"s", "skip", ""}:
        return LabelAction(kind="skip")
    if normalized in {"n", "none", "0"}:
        return LabelAction(kind="save")

    selected_ids: list[int] = []
    tokens = normalized.replace(",", " ").split()
    if not tokens:
        return LabelAction(kind="skip")

    for token in tokens:
        if not token.isdigit():
            raise ValueError("Use 1-3, multiple numbers, n, s, or q.")
        index = int(token)
        if index < 1 or index > len(candidate_category_ids):
            raise ValueError("Candidate number is outside the shown list.")
        category_id = candidate_category_ids[index - 1]
        if category_id not in selected_ids:
            selected_ids.append(category_id)

    return LabelAction(kind="save", selected_category_ids=tuple(selected_ids))


def _read_action(
    item: CategoryLabelQueueItem,
    *,
    input_fn: Callable[[str], str],
    output: Writer,
) -> LabelAction:
    candidate_ids = tuple(candidate.id for candidate in item.candidates)
    while True:
        answer = input_fn("Choose category numbers, n=none, s=skip, q=quit: ")
        try:
            return parse_label_answer(answer, candidate_ids)
        except ValueError as error:
            output.write(f"{error}\n")


def _print_item(item: CategoryLabelQueueItem, output: Writer) -> None:
    output.write("\n")
    output.write(f"Product #{item.product.id}: {item.product.title}\n")
    output.write(f"Source: {item.product.source}\n")
    if item.product.category_raw:
        output.write(f"Raw category: {item.product.category_raw}\n")
    output.write("Candidates:\n")
    for index, candidate in enumerate(item.candidates, start=1):
        output.write(f"  {index}. {candidate.name} [{candidate.reason}]\n")


class _Stdout:
    def write(self, text: str) -> int:
        print(text, end="")
        return len(text)


if __name__ == "__main__":
    raise SystemExit(main())
