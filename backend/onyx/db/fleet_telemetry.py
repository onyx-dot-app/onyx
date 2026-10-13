"""Bounded reads for fleet telemetry snapshots."""

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import KeyedColumnElement

from onyx.db.enums import (
    AccessType,
    AccountType,
    IndexingStatus,
    PermissionSyncStatus,
    PortAttemptStatus,
    SyncStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    HierarchyFetchAttempt,
    IndexAttempt,
    IndexAttemptError,
    IndexAttemptStageMetric,
    License,
    PortAttempt,
    SyncRecord,
    User,
)

# Rows per read.
ROW_LIMIT: int = 1000
# A slow read stops here, so telemetry never adds long queries to a busy database.
_STATEMENT_TIMEOUT: str = "1500ms"
_RUNNING_INDEXING: tuple[IndexingStatus, ...] = (
    IndexingStatus.NOT_STARTED,
    IndexingStatus.IN_PROGRESS,
)
_RUNNING_PERMISSION_SYNC: tuple[PermissionSyncStatus, ...] = (
    PermissionSyncStatus.NOT_STARTED,
    PermissionSyncStatus.IN_PROGRESS,
)
_RUNNING_PORT: tuple[PortAttemptStatus, ...] = (
    PortAttemptStatus.NOT_STARTED,
    PortAttemptStatus.IN_PROGRESS,
)


def _changed_first(changed_at: Any, row_id: Any, since: datetime) -> tuple[Any, ...]:
    """Rows that changed since `since` come first, oldest first, then running rows
    from before the window. A capped read then ends where the next pass resumes."""
    return (changed_at < since, changed_at, row_id)


def limit_statement_time(db_session: Session) -> None:
    """Bound each later statement in the current transaction."""
    db_session.execute(
        select(func.set_config("statement_timeout", _STATEMENT_TIMEOUT, True))
    )


def connector_rows(db_session: Session) -> list[dict[str, Any]]:
    statement = (
        select(
            ConnectorCredentialPair.id.label("cc_pair_id"),
            ConnectorCredentialPair.connector_id,
            Connector.source,
            ConnectorCredentialPair.status,
            ConnectorCredentialPair.total_docs_indexed.label("doc_count"),
            ConnectorCredentialPair.last_successful_index_time.label("last_success_at"),
            Connector.refresh_freq.label("refresh_seconds"),
            Connector.prune_freq.label("prune_seconds"),
            ConnectorCredentialPair.auto_sync_options.is_not(None).label(
                "auto_sync_enabled"
            ),
            ConnectorCredentialPair.access_type.in_(
                (AccessType.SYNC, AccessType.SYNC_RESTRICTED)
            ).label("permission_sync_enabled"),
            Connector.connector_specific_config.label("config"),
        )
        .join(Connector, Connector.id == ConnectorCredentialPair.connector_id)
        .order_by(ConnectorCredentialPair.id)
        .limit(ROW_LIMIT)
    )
    return [dict(row) for row in db_session.execute(statement).mappings()]


def attempt_rows(db_session: Session, since: datetime) -> list[dict[str, Any]]:
    """Index attempts updated since `since`, and the ones that are still running."""
    unresolved = (IndexAttemptError.index_attempt_id == IndexAttempt.id) & (
        IndexAttemptError.is_resolved.is_(False)
    )

    def latest_error(column: Any) -> Any:
        return (
            select(func.left(column, 2048))
            .where(unresolved)
            .order_by(IndexAttemptError.id.desc())
            .limit(1)
            .scalar_subquery()
        )

    statement = (
        select(
            IndexAttempt.id.label("attempt_id"),
            IndexAttempt.connector_credential_pair_id.label("cc_pair_id"),
            ConnectorCredentialPair.connector_id,
            Connector.source,
            IndexAttempt.status,
            IndexAttempt.total_docs_indexed.label("docs_indexed"),
            IndexAttempt.total_chunks.label("chunks_indexed"),
            IndexAttempt.total_batches,
            IndexAttempt.completed_batches,
            IndexAttempt.time_started.label("started_at"),
            IndexAttempt.time_updated,
            IndexAttempt.last_progress_time.label("last_progress_at"),
            IndexAttempt.last_heartbeat_time.label("last_heartbeat_at"),
            func.left(IndexAttempt.error_msg, 2048).label("error_sample"),
            latest_error(IndexAttemptError.error_type).label("item_error_type"),
            latest_error(IndexAttemptError.failure_message).label("item_error_sample"),
            select(func.count())
            .where(unresolved)
            .scalar_subquery()
            .label("error_count"),
        )
        .join(
            ConnectorCredentialPair,
            ConnectorCredentialPair.id == IndexAttempt.connector_credential_pair_id,
        )
        .join(Connector, Connector.id == ConnectorCredentialPair.connector_id)
        .where(
            or_(
                IndexAttempt.time_updated >= since,
                IndexAttempt.status.in_(_RUNNING_INDEXING),
            ),
            IndexAttempt.is_synthetic_seed.is_(False),
        )
        .order_by(*_changed_first(IndexAttempt.time_updated, IndexAttempt.id, since))
        .limit(ROW_LIMIT)
    )
    return [dict(row) for row in db_session.execute(statement).mappings()]


def stage_rows(
    db_session: Session, attempt_ids: list[int], since: datetime
) -> list[dict[str, Any]]:
    """Stage timing summaries of these attempts that changed since `since`."""
    if not attempt_ids:
        return []
    statement = (
        select(
            IndexAttemptStageMetric.index_attempt_id.label("attempt_id"),
            IndexAttemptStageMetric.stage,
            IndexAttemptStageMetric.event_count,
            IndexAttemptStageMetric.total_duration_ms,
            IndexAttemptStageMetric.min_duration_ms,
            IndexAttemptStageMetric.max_duration_ms,
            IndexAttemptStageMetric.m2_duration_ms,
            IndexAttemptStageMetric.time_first_event.label("first_event_at"),
            IndexAttemptStageMetric.time_last_event.label("last_event_at"),
        )
        .where(
            IndexAttemptStageMetric.index_attempt_id.in_(attempt_ids),
            IndexAttemptStageMetric.time_last_event >= since,
        )
        .order_by(IndexAttemptStageMetric.time_last_event, IndexAttemptStageMetric.id)
        .limit(ROW_LIMIT)
    )
    return [dict(row) for row in db_session.execute(statement).mappings()]


def _job(
    job_id: str,
    job_type: str,
    state: str,
    *,
    entity_id: int | None,
    cc_pair_id: int | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    revision_at: datetime,
    docs_processed: int | None = 0,
    users_processed: int | None = 0,
    groups_processed: int | None = 0,
    memberships_synced: int | None = 0,
    error_count: int | None = 0,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_type": job_type,
        "state": state.lower(),
        "entity_id": entity_id,
        "cc_pair_id": cc_pair_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "revision_at": revision_at,
        "docs_processed": docs_processed or 0,
        "users_processed": users_processed or 0,
        "groups_processed": groups_processed or 0,
        "memberships_synced": memberships_synced or 0,
        "error_count": error_count or 0,
    }


def job_rows(db_session: Session, since: datetime) -> list[dict[str, Any]]:
    """Background jobs that changed since `since` or are still running, in one shape."""
    sync_revision = func.coalesce(SyncRecord.sync_end_time, SyncRecord.sync_start_time)
    syncs = db_session.execute(
        select(
            SyncRecord.id,
            SyncRecord.entity_id,
            SyncRecord.sync_type,
            SyncRecord.sync_status,
            SyncRecord.num_docs_synced,
            SyncRecord.sync_start_time,
            SyncRecord.sync_end_time,
            sync_revision.label("revision_at"),
        )
        .where(
            or_(
                SyncRecord.sync_status == SyncStatus.IN_PROGRESS,
                SyncRecord.sync_start_time >= since,
                SyncRecord.sync_end_time >= since,
            )
        )
        .order_by(*_changed_first(sync_revision, SyncRecord.id, since))
        .limit(ROW_LIMIT)
    )
    jobs: list[dict[str, Any]] = [
        _job(
            f"sync:{sync.id}",
            sync.sync_type.value,
            sync.sync_status.value,
            entity_id=sync.entity_id,
            cc_pair_id=None,
            started_at=sync.sync_start_time,
            ended_at=sync.sync_end_time,
            revision_at=sync.revision_at,
            docs_processed=sync.num_docs_synced,
        )
        for sync in syncs
    ]
    permission_revision = func.coalesce(
        DocPermissionSyncAttempt.time_finished,
        DocPermissionSyncAttempt.time_started,
        DocPermissionSyncAttempt.time_created,
    )
    permission_syncs = db_session.execute(
        select(
            permission_revision.label("revision_at"),
            DocPermissionSyncAttempt.id,
            DocPermissionSyncAttempt.connector_credential_pair_id,
            DocPermissionSyncAttempt.status,
            DocPermissionSyncAttempt.total_docs_synced,
            DocPermissionSyncAttempt.docs_with_permission_errors,
            DocPermissionSyncAttempt.time_created,
            DocPermissionSyncAttempt.time_started,
            DocPermissionSyncAttempt.time_finished,
        )
        .where(
            or_(
                DocPermissionSyncAttempt.status.in_(_RUNNING_PERMISSION_SYNC),
                DocPermissionSyncAttempt.time_created >= since,
                DocPermissionSyncAttempt.time_finished >= since,
            )
        )
        .order_by(
            *_changed_first(permission_revision, DocPermissionSyncAttempt.id, since)
        )
        .limit(ROW_LIMIT)
    )
    jobs.extend(
        _job(
            f"permission:{attempt.id}",
            "permission_sync",
            attempt.status.value,
            entity_id=attempt.connector_credential_pair_id,
            cc_pair_id=attempt.connector_credential_pair_id,
            started_at=attempt.time_started,
            ended_at=attempt.time_finished,
            revision_at=attempt.revision_at,
            docs_processed=attempt.total_docs_synced,
            error_count=attempt.docs_with_permission_errors,
        )
        for attempt in permission_syncs
    )
    group_revision = func.coalesce(
        ExternalGroupPermissionSyncAttempt.time_finished,
        ExternalGroupPermissionSyncAttempt.time_started,
        ExternalGroupPermissionSyncAttempt.time_created,
    )
    group_syncs = db_session.execute(
        select(
            group_revision.label("revision_at"),
            ExternalGroupPermissionSyncAttempt.id,
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id,
            ExternalGroupPermissionSyncAttempt.status,
            ExternalGroupPermissionSyncAttempt.total_users_processed,
            ExternalGroupPermissionSyncAttempt.total_groups_processed,
            ExternalGroupPermissionSyncAttempt.total_group_memberships_synced,
            ExternalGroupPermissionSyncAttempt.error_message.is_not(None).label(
                "has_error"
            ),
            ExternalGroupPermissionSyncAttempt.time_created,
            ExternalGroupPermissionSyncAttempt.time_started,
            ExternalGroupPermissionSyncAttempt.time_finished,
        )
        .where(
            or_(
                ExternalGroupPermissionSyncAttempt.status.in_(_RUNNING_PERMISSION_SYNC),
                ExternalGroupPermissionSyncAttempt.time_created >= since,
                ExternalGroupPermissionSyncAttempt.time_finished >= since,
            )
        )
        .order_by(
            *_changed_first(
                group_revision, ExternalGroupPermissionSyncAttempt.id, since
            )
        )
        .limit(ROW_LIMIT)
    )
    jobs.extend(
        _job(
            f"group:{group.id}",
            "group_sync",
            group.status.value,
            entity_id=group.connector_credential_pair_id,
            cc_pair_id=group.connector_credential_pair_id,
            started_at=group.time_started,
            ended_at=group.time_finished,
            revision_at=group.revision_at,
            users_processed=group.total_users_processed,
            groups_processed=group.total_groups_processed,
            memberships_synced=group.total_group_memberships_synced,
            error_count=int(group.has_error),
        )
        for group in group_syncs
    )
    hierarchy_fetches = db_session.execute(
        select(
            HierarchyFetchAttempt.id,
            HierarchyFetchAttempt.connector_credential_pair_id,
            HierarchyFetchAttempt.status,
            HierarchyFetchAttempt.error_msg.is_not(None).label("has_error"),
            HierarchyFetchAttempt.time_started,
            HierarchyFetchAttempt.time_updated,
        )
        .where(
            or_(
                HierarchyFetchAttempt.status.in_(_RUNNING_INDEXING),
                HierarchyFetchAttempt.time_updated >= since,
            )
        )
        .order_by(
            *_changed_first(
                HierarchyFetchAttempt.time_updated, HierarchyFetchAttempt.id, since
            )
        )
        .limit(ROW_LIMIT)
    )
    jobs.extend(
        _job(
            f"hierarchy:{hierarchy.id}",
            "hierarchy",
            hierarchy.status.value,
            entity_id=hierarchy.connector_credential_pair_id,
            cc_pair_id=hierarchy.connector_credential_pair_id,
            started_at=hierarchy.time_started,
            ended_at=hierarchy.time_updated if hierarchy.status.is_terminal() else None,
            revision_at=hierarchy.time_updated,
            error_count=int(hierarchy.has_error),
        )
        for hierarchy in hierarchy_fetches
    )
    ports = db_session.execute(
        select(
            PortAttempt.id,
            PortAttempt.cc_pair_id,
            PortAttempt.status,
            PortAttempt.docs_ported,
            PortAttempt.error_msg.is_not(None).label("has_error"),
            PortAttempt.time_started,
            PortAttempt.time_completed,
            PortAttempt.time_updated,
        )
        .where(
            or_(
                PortAttempt.status.in_(_RUNNING_PORT),
                PortAttempt.time_updated >= since,
            )
        )
        .order_by(*_changed_first(PortAttempt.time_updated, PortAttempt.id, since))
        .limit(ROW_LIMIT)
    )
    jobs.extend(
        _job(
            f"port:{port.id}",
            "migration",
            port.status.value,
            entity_id=port.cc_pair_id,
            cc_pair_id=port.cc_pair_id,
            started_at=port.time_started,
            ended_at=port.time_completed,
            revision_at=port.time_updated,
            docs_processed=port.docs_ported,
            error_count=int(port.has_error),
        )
        for port in ports
    )
    return jobs


def email_domain_rows(db_session: Session) -> list[dict[str, Any]]:
    """Each email domain of standard accounts, with its first signup time."""
    email: KeyedColumnElement[Any] = User.__table__.c.email
    domain = func.lower(func.split_part(email, "@", 2))
    statement = (
        select(
            domain.label("domain"),
            func.min(User.created_at).label("first_signup_at"),
        )
        .where(
            User.account_type == AccountType.STANDARD,
            email.regexp_match("^[^@]+@[^@]+$"),
        )
        .group_by(domain)
        .order_by(domain)
        .limit(ROW_LIMIT)
    )
    return [dict(row) for row in db_session.execute(statement).mappings()]


def license_row(db_session: Session) -> dict[str, Any]:
    """Whether a license is stored, and since when. Never the license itself."""
    present = func.length(License.license_data) > 0
    statement = select(
        func.coalesce(func.bool_or(present), False).label("license_present"),
        func.min(License.created_at).filter(present).label("first_set_at"),
    )
    return dict(db_session.execute(statement).mappings().one())
