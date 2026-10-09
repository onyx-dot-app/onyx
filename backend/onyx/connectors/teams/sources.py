"""What the connector asks of every content source, whatever it indexes."""

import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TypeVar

import requests

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import SlimDocument
from onyx.connectors.teams.refusals import is_permanent
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.batching import batch_generator
from onyx.utils.threadpool_concurrency import drain

T = TypeVar("T")

# Pruning and permission sync both run the slim walk, so its signals name the
# walk and not either caller.
SLIM_WALK = "teams_slim_walk"
# The runner's lock lives on the progress reports, so a long batch reports
# again every so many documents it yields, from the consuming thread.
PROGRESS_EVERY_DOCUMENTS = 500


class SlimWalk:
    """One pruning or permission sync walk: ids alone, or ids with their
    readers. Readers cost calls that pruning would throw away."""

    def __init__(
        self,
        start: SecondsSinceUnixEpoch,
        callback: IndexingHeartbeatInterface | None,
        with_readers: bool,
        lists_threads: bool = True,
    ) -> None:
        self.start: SecondsSinceUnixEpoch = start
        self.callback: IndexingHeartbeatInterface | None = callback
        self.with_readers: bool = with_readers
        # False when the caller has no use for threads: the group a thread
        # names never changes, and the group sync says who is in it.
        self.lists_threads: bool = lists_threads
        # Workers report from their own threads and the runner's callback is
        # not built for that, so every report goes through one lock.
        self._signal_lock: threading.Lock = threading.Lock()

    def raise_if_stopped(self) -> None:
        if self.callback and self.callback.should_stop():
            raise RuntimeError(f"{SLIM_WALK}: Stop signal detected")

    def report_progress(self, amount: int) -> None:
        if self.callback is None:
            return
        with self._signal_lock:
            self.callback.progress(SLIM_WALK, amount)

    def page_signals(self) -> None:
        """What a listing gets before each of its pages, on whichever worker
        reads it: a stop check and a progress report, so a run of listings
        that page for long and yield nothing still keeps the runner's lock."""
        self.raise_if_stopped()
        self.report_progress(0)

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
        those reports. Each listing signals before every page of its own."""
        yielded: int = 0
        for items_batch in batch_generator(items, batch or workers):
            self.raise_if_stopped()
            self.report_progress(len(items_batch))
            for document in drain(items_batch, listing, workers):
                yielded += 1
                if yielded % PROGRESS_EVERY_DOCUMENTS == 0:
                    self.report_progress(0)
                yield document

    def batch_signals(self) -> None:
        """The stop and progress signals the runner gets before every batch."""
        self.raise_if_stopped()
        self.report_progress(1)


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
            self.walk.page_signals()
        self.pages += 1

    def lost_access(self, error: requests.RequestException) -> bool:
        return self.pages <= 1 and is_permanent(error)
