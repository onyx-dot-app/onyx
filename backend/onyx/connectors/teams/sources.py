"""What the connector asks of every content source, whatever it indexes."""

from collections.abc import Callable, Iterable, Iterator
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
    ) -> Iterator[SlimDocument]:
        """``workers`` items at a time, with a stop check and a progress report
        per batch: the runner's lock lives on those reports. Each listing honors
        a stop before every page of its own."""
        for batch in batch_generator(items, workers):
            self.raise_if_stopped()
            if self.callback:
                self.callback.progress(SLIM_WALK, len(batch))
            if workers == 1:
                for item in batch:
                    yield from listing(item)
                continue
            yield from parallel_yield(
                [listing(item) for item in batch], max_workers=workers
            )

    def batch_signals(self) -> None:
        """The stop and progress signals the runner gets before every batch."""
        self.raise_if_stopped()
        if self.callback:
            self.callback.progress(SLIM_WALK, 1)


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
