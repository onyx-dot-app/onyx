"""What the connector asks of every content source, whatever it indexes."""

from dataclasses import dataclass

from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


@dataclass
class SlimWalk:
    """One pruning or permission sync walk: ids alone, or ids with their
    readers. Readers cost calls that pruning would throw away."""

    start: SecondsSinceUnixEpoch
    callback: IndexingHeartbeatInterface | None
    with_readers: bool
