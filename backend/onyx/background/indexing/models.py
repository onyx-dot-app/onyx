from datetime import datetime

from pydantic import BaseModel

from onyx.db.models import IndexAttemptError


class IndexAttemptErrorPydantic(BaseModel):
    id: int
    connector_credential_pair_id: int

    document_id: str | None
    document_link: str | None

    entity_id: str | None
    failed_time_range_start: datetime | None
    failed_time_range_end: datetime | None

    failure_message: str
    is_resolved: bool = False

    time_created: datetime

    index_attempt_id: int

    @classmethod
    def from_model(cls, model: IndexAttemptError) -> "IndexAttemptErrorPydantic":
        return cls(
            id=model.id,
            connector_credential_pair_id=model.connector_credential_pair_id,
            document_id=model.document_id,
            document_link=model.document_link,
            entity_id=model.entity_id,
            failed_time_range_start=model.failed_time_range_start,
            failed_time_range_end=model.failed_time_range_end,
            failure_message=model.failure_message,
            is_resolved=model.is_resolved,
            time_created=model.time_created,
            index_attempt_id=model.index_attempt_id,
        )
