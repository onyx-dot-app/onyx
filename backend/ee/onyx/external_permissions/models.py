from datetime import datetime

from pydantic import BaseModel


class DocSyncResume(BaseModel):
    """Where a stopped doc sync crawl left off, and the window it was covering."""

    checkpoint_json: str
    poll_range_start: datetime | None
    poll_range_end: datetime
