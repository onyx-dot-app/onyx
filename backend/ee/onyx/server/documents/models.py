from datetime import datetime

from pydantic import BaseModel, Field

from ee.onyx.server.user_group.models import MinimalUserGroupSnapshot
from onyx.db.enums import SyncAttemptErrorResolvedReason, SyncEntityKind
from onyx.db.models import SyncAttemptError
from onyx.server.documents.models import CC_PAIR_RUN_BATCH_MAX


class CCPairDataAccessUpdateRequest(BaseModel):
    group_ids: list[int]


class CCPairDataAccess(BaseModel):
    # Only the groups the caller can see.
    groups: list[MinimalUserGroupSnapshot]


class SyncAttemptErrorSnapshot(BaseModel):
    """A user or group a group sync skipped whole because the source could not
    read it."""

    id: int
    connector_credential_pair_id: int
    external_group_sync_attempt_id: int
    entity_kind: SyncEntityKind
    entity_id: str
    entity_name: str | None
    failure_message: str
    time_created: datetime
    is_resolved: bool
    resolved_reason: SyncAttemptErrorResolvedReason | None
    resolved_at: datetime | None

    @classmethod
    def from_model(cls, model: SyncAttemptError) -> "SyncAttemptErrorSnapshot":
        return cls(
            id=model.id,
            connector_credential_pair_id=model.connector_credential_pair_id,
            external_group_sync_attempt_id=model.external_group_sync_attempt_id,
            entity_kind=model.entity_kind,
            entity_id=model.entity_id,
            entity_name=model.entity_name,
            failure_message=model.failure_message,
            time_created=model.time_created,
            is_resolved=model.is_resolved,
            resolved_reason=model.resolved_reason,
            resolved_at=model.resolved_at,
        )


class SyncAttemptErrorsResolveRequest(BaseModel):
    error_ids: list[int] = Field(min_length=1, max_length=CC_PAIR_RUN_BATCH_MAX)


class SyncAttemptErrorsResolveResponse(BaseModel):
    resolved_count: int
