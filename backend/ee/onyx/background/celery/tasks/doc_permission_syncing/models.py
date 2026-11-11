from datetime import datetime

from pydantic import BaseModel


class SavedDocSyncCheckpoint(BaseModel):
    """The checkpoint file: the crawl state plus what decides whether a later
    attempt may continue it."""

    attempt_id: int
    saved_at: datetime
    connector_config_hash: str | None
    poll_range_start: datetime | None
    poll_range_end: datetime
    checkpoint_json: str
