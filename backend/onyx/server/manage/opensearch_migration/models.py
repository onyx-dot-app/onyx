from datetime import datetime

from pydantic import BaseModel


class OpenSearchMigrationStatusResponse(BaseModel):
    model_config = {"frozen": True}
    total_chunks_migrated: int
    created_at: datetime | None
    migration_completed_at: datetime | None


class OpenSearchRetrievalStatusRequest(BaseModel):
    model_config = {"frozen": True}
    enable_opensearch_retrieval: bool


class OpenSearchRetrievalStatusResponse(BaseModel):
    model_config = {"frozen": True}
    enable_opensearch_retrieval: bool
