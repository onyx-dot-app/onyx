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
    a single pair's group syncs to the history its source shares across pairs,
    and ``shared_sources`` widens many pairs' group syncs to every pair of those
    sources, since such a source logs its one sync against whichever pair ran it.
    A failed run is superseded once a newer run of its kind finishes on the
    same history. ``superseded`` False leaves those runs out, True keeps only
    them, or adds them to what ``errors`` keeps, as both are closed items.
    ``resolved`` reads the runs an admin resolved the same way."""

    cc_pair_ids: list[int]
    source: DocumentSource | None
    shared_sources: set[DocumentSource]
    since: datetime | None
    # Exclusive, so back-to-back windows never share a run.
    until: datetime | None
    error_query: str | None
    status_groups: set[CCPairRunStatusGroup] | None
    errors: CCPairRunErrors | None
    superseded: bool | None
    resolved: bool | None = None


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
