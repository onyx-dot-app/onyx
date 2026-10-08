"""What the connector asks of every content source, whatever it indexes."""

from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import TypeVar

import requests

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import SlimDocument
from onyx.connectors.teams.refusals import is_permanent
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.batching import batch_generator
from onyx.utils.threadpool_concurrency import parallel_yield

T = TypeVar("T")

# Pruning and permission sync both run the slim walk, so its signals name the
# walk and not either caller.
SLIM_WALK = "teams_slim_walk"
# The runner's lock lives on the progress reports, so a long batch reports
# again every so many documents it yields, from the consuming thread.
PROGRESS_EVERY_DOCUMENTS = 500


@dataclass
class SlimWalk:
    """One pruning or permission sync walk: ids alone, or ids with their
    readers. Readers cost calls that pruning would throw away."""

    start: SecondsSinceUnixEpoch
    callback: IndexingHeartbeatInterface | None
    with_readers: bool
    # False when the caller has no use for threads: the group a thread names
    # never changes, and the group sync says who is in it.
    lists_threads: bool = True

    def raise_if_stopped(self) -> None:
        if self.callback and self.callback.should_stop():
            raise RuntimeError(f"{SLIM_WALK}: Stop signal detected")

    def fan_out(
        self,
        items: Iterable[T],
        listing: Callable[[T], Iterator[SlimDocument]],
        workers: int,
        batch: int | None = None,
    ) -> Iterator[SlimDocument]:
        """Batches of ``batch`` items drained by ``workers``, with a stop check
        and a progress report per batch and again every
        PROGRESS_EVERY_DOCUMENTS yielded, since the runner's lock lives on
        those reports. Each listing honors a stop before every page of its own."""
        yielded = 0
        for items_batch in batch_generator(items, batch or workers):
            self.raise_if_stopped()
            if self.callback:
                self.callback.progress(SLIM_WALK, len(items_batch))
            for document in drain(items_batch, listing, workers):
                yielded += 1
                if self.callback and yielded % PROGRESS_EVERY_DOCUMENTS == 0:
                    self.callback.progress(SLIM_WALK, 0)
                yield document

    def batch_signals(self) -> None:
        """The stop and progress signals the runner gets before every batch."""
        self.raise_if_stopped()
        if self.callback:
            self.callback.progress(SLIM_WALK, 1)


R = TypeVar("R")


def drain(
    items: Sequence[T], listing: Callable[[T], Iterator[R]], workers: int
) -> Iterator[R]:
    """Every item listed, ``workers`` at a time, each worker taking the next
    item off a shared queue so a slow item holds back only its own worker."""
    if workers <= 1 or len(items) <= 1:
        for item in items:
            yield from listing(item)
        return
    queue: deque[T] = deque(items)

    def worker() -> Iterator[R]:
        while queue:
            try:
                item = queue.popleft()
            except IndexError:
                return
            yield from listing(item)

    yield from parallel_yield(
        [worker() for _ in range(min(workers, len(items)))], max_workers=workers
    )


@dataclass
class PagedListing:
    """One paged listing of a walk. Refused at its first request, the app lost
    access: the listing is empty, so pruning removes what it held and indexing
    records nothing. Refused after it answered, the listing broke and the rest
    still exists, so the attempt fails and the next one decides."""

    walk: SlimWalk | None = None
    pages: int = 0

    def before_page(self) -> None:
        if self.walk is not None:
            self.walk.raise_if_stopped()
        self.pages += 1

    def lost_access(self, error: requests.RequestException) -> bool:
        return self.pages <= 1 and is_permanent(error)
