from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from stroyhub.db import SessionLocal
from stroyhub.ml.category_queue import CategoryLabelQueue, CategoryLabelQueueItem
from stroyhub.ml.labels import CategoryLabelRecord, CategoryLabelStore

LabelActionKind = Literal["save", "skip", "quit"]

# ANSI colour helpers
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_BLUE = "\033[34m"

_REASON_COLOURS: dict[str, str] = {
    "current_category": _GREEN,
    "rule_prediction": _CYAN,
    "text_signal": _YELLOW,
    "nearby_category": _BLUE,
    "fallback": _DIM,
}


def _c(colour: str, text: str) -> str:
    return f"{colour}{text}{_RESET}"


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
    _configure_stdin()
    parser = argparse.ArgumentParser(
        description="Label product/category matches for the category verifier dataset."
    )
    parser.add_argument("--labels-path", type=str)
    parser.add_argument("--source")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--labeled-by", default="cli")
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--category-raw", type=str)
    args = parser.parse_args(argv)

    label_store = (
        CategoryLabelStore.default()
        if args.labels_path is None
        else CategoryLabelStore.from_path(args.labels_path)
    )

    with SessionLocal() as session:
        queue = CategoryLabelQueue(
            session,
            label_store,
            source=args.source,
            shuffle=args.shuffle,
            category_raw=args.category_raw,
        )
        result = run_label_session(
            queue,
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
    labeled_total = queue.labeled_count()
    unlabeled_total = queue.unlabeled_count()

    while limit is None or saved < limit:
        item = queue.next_item(excluded_product_ids=excluded_product_ids)
        if item is None:
            return LabelSessionResult(
                saved=saved,
                skipped=skipped,
                quit_requested=False,
                exhausted=True,
            )

        remaining = max(0, unlabeled_total - saved)
        _print_item(item, output, labeled=labeled_total + saved, remaining=remaining)
        action = _read_action(item, input_fn=input_fn, output=output, saved=saved, skipped=skipped)
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
    saved: int,
    skipped: int,
) -> LabelAction:
    candidate_ids = tuple(candidate.id for candidate in item.candidates)
    prompt = f"[session: {saved} saved, {skipped} skipped] Choose numbers, n=none, s=skip, q=quit: "
    while True:
        try:
            answer = input_fn(prompt)
        except UnicodeDecodeError:
            output.write("Could not decode input. Use 1-3, n, s, or q.\n")
            continue
        try:
            return parse_label_answer(answer, candidate_ids)
        except ValueError as error:
            output.write(f"{error}\n")


def _print_item(
    item: CategoryLabelQueueItem,
    output: Writer,
    *,
    labeled: int,
    remaining: int,
) -> None:
    output.write("\n")
    output.write(_c(_DIM, "-" * 72) + "\n")
    output.write(_c(_DIM, f"[{labeled} labeled / ~{remaining} remaining]") + "\n")
    output.write(_c(_BOLD, f"Product #{item.product.id}: {item.product.title}") + "\n")
    output.write(f"Source: {_c(_CYAN, item.product.source)}")
    if item.product.shop_name:
        output.write(f"  Shop: {_c(_CYAN, item.product.shop_name)}")
    output.write("\n")
    if item.product.category_raw:
        output.write(f"Raw category: {_c(_YELLOW, item.product.category_raw)}\n")
    output.write("Candidates:\n")
    for index, candidate in enumerate(item.candidates, start=1):
        colour = _REASON_COLOURS.get(candidate.reason, "")
        reason_str = _c(colour, f"[{candidate.reason}]") if colour else f"[{candidate.reason}]"
        output.write(f"  {_c(_GREEN, str(index))}. {candidate.name} {reason_str}\n")


def _configure_stdin() -> None:
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


class _Stdout:
    def write(self, text: str) -> int:
        print(text, end="")
        return len(text)


if __name__ == "__main__":
    raise SystemExit(main())
