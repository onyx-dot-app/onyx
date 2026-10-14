from datetime import datetime

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.db.enums import CCPairRunErrors, CCPairRunKind, CCPairRunStatusGroup
from onyx.db.models import (
    CapabilityCheckRun,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    SyncRecord,
)


class CCPairRunFilter(BaseModel):
    """What narrows a run feed. ``None`` leaves that axis open. ``source`` widens
    a single pair's group syncs to the history its source shares across pairs."""

    cc_pair_ids: list[int]
    source: DocumentSource | None
    since: datetime | None
    error_query: str | None
    status_groups: set[CCPairRunStatusGroup] | None
    errors: CCPairRunErrors | None


class CCPairRunPage(BaseModel):
    """One page of runs: their order as (kind, id), and each kind's rows by id."""

    # ORM rows ride inside, as in db/projects.py
    model_config = ConfigDict(arbitrary_types_allowed=True)

    order: list[tuple[CCPairRunKind, int]]
    index_attempts: dict[int, IndexAttempt]
    doc_permission_syncs: dict[int, DocPermissionSyncAttempt]
    group_syncs: dict[int, ExternalGroupPermissionSyncAttempt]
    # Prune runs are the pair's pruning sync records.
    prune_runs: dict[int, SyncRecord]
    check_runs: dict[int, CapabilityCheckRun]
