"""What the connector asks of every content source, whatever it indexes."""

from dataclasses import dataclass

import requests

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.teams.refusals import is_permanent
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

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

    def raise_if_stopped(self) -> None:
        if self.callback and self.callback.should_stop():
            raise RuntimeError(f"{SLIM_WALK}: Stop signal detected")

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
