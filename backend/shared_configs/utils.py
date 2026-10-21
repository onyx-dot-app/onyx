from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def batch_list(
    lst: list[T],
    batch_size: int,
) -> list[list[T]]:
    return [lst[i : i + batch_size] for i in range(0, len(lst), batch_size)]


def batch_within_token_budget(
    items: list[T],
    max_items: int,
    max_tokens: int,
    estimate_tokens: Callable[[T], int],
) -> list[list[T]]:
    """Batch on whichever cap comes first: item count or total tokens.

    Several embedding providers cap a request on the SUM of tokens across its
    inputs, not just on the number of inputs, so an item-count batch alone can
    still break the request. ``estimate_tokens`` should run high: over-counting
    costs an extra request, under-counting costs a rejected one.

    An item that exceeds ``max_tokens`` on its own is placed in a batch alone,
    where provider-side truncation applies.
    """
    batches: list[list[T]] = []
    current_batch: list[T] = []
    current_tokens = 0

    for item in items:
        item_tokens = estimate_tokens(item)
        if current_batch and (
            len(current_batch) >= max_items or current_tokens + item_tokens > max_tokens
        ):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0

        current_batch.append(item)
        current_tokens += item_tokens

    if current_batch:
        batches.append(current_batch)

    return batches
