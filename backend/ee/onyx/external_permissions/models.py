from datetime import datetime

from pydantic import BaseModel

from onyx.db.enums import SyncEntityKind


class DocSyncResume(BaseModel):
    """Where a stopped doc sync crawl left off, and the window it was covering."""

    checkpoint_json: str
    poll_range_start: datetime | None
    poll_range_end: datetime


class SyncEntityFailure(BaseModel):
    """A user or group a group sync could not read. A group is never yielded
    with partial membership. A failed Drive user's remaining folders are
    skipped, and the folders already read stay with the permissions read for
    them. The stale sweep removes whatever was skipped."""

    kind: SyncEntityKind
    id: str
    name: str | None = None
    message: str
