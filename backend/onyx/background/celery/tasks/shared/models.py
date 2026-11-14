from datetime import datetime

from pydantic import BaseModel

from onyx.document_index.interfaces import MetadataUpdateRequest


class CleanupBatchPlan(BaseModel):
    """What phase 1 decided for a batch, split by the links each document keeps
    once this cc_pair's link is gone."""

    # Linked only to this cc_pair: drop the chunks and the rows.
    delete_ids: list[str] = []
    # Still linked elsewhere: unlinked here, re-sync the index.
    update_ids: list[str] = []
    update_requests: list[MetadataUpdateRequest] = []
    # The last_modified stamped on update_ids, their sync watermark.
    update_modified_at: datetime | None = None
    num_skipped: int = 0
