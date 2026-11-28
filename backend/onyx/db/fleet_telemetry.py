"""Bounded reads for fleet telemetry snapshots."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import Date, cast, distinct, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import KeyedColumnElement

from onyx.configs.constants import MessageType
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.enums import (
    AccessType,
    AccountType,
    IndexingStatus,
    PermissionSyncStatus,
    PortAttemptStatus,
    SyncStatus,
    UserFileStatus,
)
from onyx.db.models import (
    BuildSession,
    ChatMessage,
    ChatSession,
    Connector,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    DocumentByConnectorCredentialPair,
    DocumentSet,
    ExternalGroupPermissionSyncAttempt,
    HierarchyFetchAttempt,
    IndexAttempt,
    IndexAttemptError,
    IndexAttemptStageMetric,
    License,
    LLMProvider,
    MCPServer,
    Persona,
    PortAttempt,
    SlackBot,
    SSOProvider,
    SyncRecord,
    Tool,
    User,
    UserFile,
)
from onyx.server.documents.models import ConnectorCredentialPairIdentifier

# Rows per read.
ROW_LIMIT: int = 1000
# Error text read for classification. Only its category leaves the deployment.
ERROR_SAMPLE_CHARS: int = 2048
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
            ConnectorCredentialPair.credential_id,
            Connector.source,
            ConnectorCredentialPair.status,
            ConnectorCredentialPair.last_successful_index_time.label("last_success_at"),
            Connector.refresh_freq.label("refresh_seconds"),
            Connector.prune_freq.label("prune_seconds"),
            ConnectorCredentialPair.auto_sync_options.is_not(None).label(
                "auto_sync_enabled"
            ),
            ConnectorCredentialPair.access_type.in_(
                (AccessType.SYNC, AccessType.SYNC_RESTRICTED)
            ).label("permission_sync_enabled"),
            ConnectorCredentialPair.last_time_perm_sync.label(
                "last_permission_sync_at"
            ),
            ConnectorCredentialPair.last_time_external_group_sync.label(
                "last_group_sync_at"
            ),
            ConnectorCredentialPair.perm_sync_pending_since.label(
                "permission_sync_pending_since"
            ),
            Connector.connector_specific_config.label("config"),
        )
        .join(Connector, Connector.id == ConnectorCredentialPair.connector_id)
        .order_by(ConnectorCredentialPair.id)
        .limit(ROW_LIMIT)
    )
    rows = [dict(row) for row in db_session.execute(statement).mappings()]
    # Match the admin count: only documents indexed for this exact pair.
    counts = {
        (connector_id, credential_id): count
        for connector_id, credential_id, count in get_document_counts_for_cc_pairs(
            db_session,
            [
                ConnectorCredentialPairIdentifier(
                    connector_id=row["connector_id"],
                    credential_id=row["credential_id"],
                )
                for row in rows
            ],
        )
    }
    for row in rows:
        row["doc_count"] = counts.get(
            (row["connector_id"], row.pop("credential_id")), 0
        )
    return rows


def has_indexed_connectors__no_commit(db_session: Session) -> bool:
    # Exclude the seeded upload connector; scan beyond the inventory reporting cap.
    return bool(
        db_session.scalar(
            select(
                select(ConnectorCredentialPair.id)
                .join(
                    DocumentByConnectorCredentialPair,
                    (
                        DocumentByConnectorCredentialPair.connector_id
                        == ConnectorCredentialPair.connector_id
                    )
                    & (
                        DocumentByConnectorCredentialPair.credential_id
                        == ConnectorCredentialPair.credential_id
                    ),
                )
                .where(
                    ConnectorCredentialPair.connector_id > 0,
                    DocumentByConnectorCredentialPair.has_been_indexed.is_(True),
                )
                .exists()
            )
        )
    )


def attempt_rows(db_session: Session, since: datetime) -> list[dict[str, Any]]:
    """Index attempts updated since `since`, and the ones that are still running."""
    unresolved = (IndexAttemptError.index_attempt_id == IndexAttempt.id) & (
        IndexAttemptError.is_resolved.is_(False)
    )

    def latest_error(column: Any) -> Any:
        return (
            select(func.left(column, ERROR_SAMPLE_CHARS))
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
            IndexAttempt.end_time.label("ended_at"),
            IndexAttempt.last_progress_time.label("last_progress_at"),
            IndexAttempt.last_heartbeat_time.label("last_heartbeat_at"),
            func.left(IndexAttempt.error_msg, ERROR_SAMPLE_CHARS).label("error_sample"),
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
    error_sample: str | None = None,
    last_progress_at: datetime | None = None,
    last_heartbeat_at: datetime | None = None,
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
        "error_sample": error_sample,
        "last_progress_at": last_progress_at,
        "last_heartbeat_at": last_heartbeat_at,
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
            func.left(DocPermissionSyncAttempt.error_message, ERROR_SAMPLE_CHARS).label(
                "error_sample"
            ),
            DocPermissionSyncAttempt.time_created,
            DocPermissionSyncAttempt.time_started,
            DocPermissionSyncAttempt.time_finished,
            DocPermissionSyncAttempt.last_progress_at,
            DocPermissionSyncAttempt.heartbeat_at,
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
            error_sample=attempt.error_sample,
            last_progress_at=attempt.last_progress_at,
            last_heartbeat_at=attempt.heartbeat_at,
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
            func.left(
                ExternalGroupPermissionSyncAttempt.error_message, ERROR_SAMPLE_CHARS
            ).label("error_sample"),
            ExternalGroupPermissionSyncAttempt.time_created,
            ExternalGroupPermissionSyncAttempt.time_started,
            ExternalGroupPermissionSyncAttempt.time_finished,
            ExternalGroupPermissionSyncAttempt.last_progress_at,
            ExternalGroupPermissionSyncAttempt.heartbeat_at,
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
            error_sample=group.error_sample,
            last_progress_at=group.last_progress_at,
            last_heartbeat_at=group.heartbeat_at,
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


class StandardUserCounts(NamedTuple):
    total: int
    active: int


def standard_user_counts(db_session: Session) -> StandardUserCounts:
    """How many standard accounts exist, and how many are not deactivated.
    Never who they are."""
    is_active: KeyedColumnElement[Any] = User.__table__.c.is_active
    statement = select(
        func.count(),
        func.count().filter(is_active.is_(True)),
    ).where(User.account_type == AccountType.STANDARD)
    total, active = db_session.execute(statement).one()
    return StandardUserCounts(total=total, active=active)


def license_row(db_session: Session) -> dict[str, Any]:
    """Whether a license is stored, and since when. Never the license itself."""
    present = func.length(License.license_data) > 0
    statement = select(
        func.coalesce(func.bool_or(present), False).label("license_present"),
        func.min(License.created_at).filter(present).label("first_set_at"),
    )
    return dict(db_session.execute(statement).mappings().one())


# Message IDs grow with send time, but rows that commit late can trail by a little.
# Each ID bound searches this much further, and the reads still filter on send time.
_ID_BOUND_SLACK: timedelta = timedelta(hours=1)
# Standard accounts by how many questions each asked in 7 days.
QUERY_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("q1", 1, 1),
    ("q2_5", 2, 5),
    ("q6_20", 6, 20),
    ("q21_50", 21, 50),
    ("q51_plus", 51, None),
)


def _user_id() -> KeyedColumnElement[Any]:
    return User.__table__.c.id


def _questions() -> Any:
    """User chat messages outside agent sub-sessions: the questions people ask."""
    return (
        select()
        .select_from(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.message_type == MessageType.USER,
            ChatSession.spawned_by_message_id.is_(None),
        )
    )


def message_id_at(db_session: Session, at: datetime) -> int:
    """The lowest chat message ID sent at or after `at`, less some slack.

    chat_message has no index on its send time, so a time range there scans
    the table. A binary search over the primary key finds the ID bound with
    about 30 indexed reads, and later reads scan only that ID range."""
    target: datetime = at - _ID_BOUND_SLACK
    low, high = db_session.execute(
        select(func.min(ChatMessage.id), func.max(ChatMessage.id))
    ).one()
    if low is None:
        return 0
    high += 1
    while low < high:
        middle: int = (low + high) // 2
        row = db_session.execute(
            select(ChatMessage.id, ChatMessage.time_sent)
            .where(ChatMessage.id >= middle)
            .order_by(ChatMessage.id)
            .limit(1)
        ).first()
        if row is None or row.time_sent >= target:
            high = middle
        else:
            low = row.id + 1
    return low


def first_question_at(db_session: Session) -> datetime | None:
    """When the first question was asked. Reads in ID order, so it stops at the first
    user message. A sub-session cannot start before the session that spawned it."""
    return db_session.scalar(
        select(ChatMessage.time_sent)
        .where(ChatMessage.message_type == MessageType.USER)
        .order_by(ChatMessage.id)
        .limit(1)
    )


class UsageWeek(NamedTuple):
    week_start: date
    queries: int
    sessions: int
    active_users: int


def usage_week_rows(db_session: Session, start: date, end: date) -> list[UsageWeek]:
    """Questions, sessions with a question, and active standard accounts per ISO
    week (Monday, UTC) in [start, end). Weeks without questions have no row."""
    start_at: datetime = datetime(start.year, start.month, start.day, tzinfo=UTC)
    end_at: datetime = datetime(end.year, end.month, end.day, tzinfo=UTC)
    week = cast(
        func.date_trunc("week", func.timezone("UTC", ChatMessage.time_sent)), Date
    )
    statement = (
        _questions()
        .add_columns(
            week.label("week_start"),
            func.count().label("queries"),
            func.count(distinct(ChatMessage.chat_session_id)).label("sessions"),
            func.count(distinct(_user_id()))
            .filter(User.account_type == AccountType.STANDARD)
            .label("active_users"),
        )
        .outerjoin(User, User.id == ChatSession.user_id)
        .where(
            ChatMessage.id >= message_id_at(db_session, start_at),
            ChatMessage.id < message_id_at(db_session, end_at + 2 * _ID_BOUND_SLACK),
            ChatMessage.time_sent >= start_at,
            ChatMessage.time_sent < end_at,
        )
        .group_by(week)
        .order_by(week)
        .limit(ROW_LIMIT)
    )
    return [
        UsageWeek(row.week_start, row.queries, row.sessions, row.active_users)
        for row in db_session.execute(statement)
    ]


def usage_counts(db_session: Session, now: datetime) -> dict[str, Any]:
    """Active accounts, questions, agent use, uploads and Craft sessions as counts.
    Never who asked or what."""
    day_ago: datetime = now - timedelta(days=1)
    week_ago: datetime = now - timedelta(days=7)
    month_ago: datetime = now - timedelta(days=30)
    standard = User.account_type == AccountType.STANDARD
    recent = ChatMessage.time_sent >= week_ago
    builtin = func.coalesce(Persona.builtin_persona, True)
    month = (
        ChatMessage.id >= message_id_at(db_session, month_ago),
        ChatMessage.time_sent >= month_ago,
    )
    totals = db_session.execute(
        _questions()
        .add_columns(
            func.count(distinct(_user_id()))
            .filter(standard, ChatMessage.time_sent >= day_ago)
            .label("active_users_1d"),
            func.count(distinct(_user_id()))
            .filter(standard, recent)
            .label("active_users_7d"),
            func.count(distinct(_user_id())).filter(standard).label("active_users_30d"),
            func.count().filter(recent).label("queries_7d"),
            func.count().label("queries_30d"),
            func.count().filter(recent, builtin).label("builtin"),
            func.count().filter(recent, ~builtin).label("custom"),
            func.count(distinct(ChatSession.persona_id))
            .filter(recent)
            .label("agents_used_7d"),
        )
        .outerjoin(User, User.id == ChatSession.user_id)
        .outerjoin(Persona, Persona.id == ChatSession.persona_id)
        .where(*month)
    ).one()
    per_user = (
        _questions()
        .add_columns(func.count().label("questions"))
        .join(User, User.id == ChatSession.user_id)
        .where(*month, recent, standard)
        .group_by(User.id)
        .subquery()
    )
    buckets = db_session.execute(
        select(
            *(
                func.count()
                .filter(
                    per_user.c.questions >= low,
                    *(() if high is None else (per_user.c.questions <= high,)),
                )
                .label(name)
                for name, low, high in QUERY_BUCKETS
            )
        ).select_from(per_user)
    ).one()
    uploads = db_session.execute(
        select(
            func.count().label("uploads_7d"),
            func.count()
            .filter(UserFile.status == UserFileStatus.FAILED)
            .label("failed_uploads_7d"),
        ).where(UserFile.created_at >= week_ago)
    ).one()
    craft = db_session.execute(
        select(
            func.count().filter(BuildSession.created_at >= week_ago),
            func.count(),
        )
    ).one()
    return {
        "active_users_1d": totals.active_users_1d,
        "active_users_7d": totals.active_users_7d,
        "active_users_30d": totals.active_users_30d,
        "queries_7d": totals.queries_7d,
        "queries_30d": totals.queries_30d,
        "users_by_queries_7d": dict(buckets._mapping),
        "agent_messages_7d": {"builtin": totals.builtin, "custom": totals.custom},
        "agents_used_7d": totals.agents_used_7d,
        "uploads_7d": uploads.uploads_7d,
        "failed_uploads_7d": uploads.failed_uploads_7d,
        "craft_sessions_7d": craft[0],
        "craft_sessions_total": craft[1],
    }


class SetupCounts(NamedTuple):
    counts: dict[str, int]
    # Provider type as stored, and how many providers have it.
    llm_providers: list[tuple[str, int]]


def setup_counts(db_session: Session) -> SetupCounts:
    """How much is configured. Never names, URLs or settings."""

    def total(model: Any, *where: Any) -> Any:
        return select(func.count()).select_from(model).where(*where).scalar_subquery()

    counts = db_session.execute(
        select(
            total(
                Persona, Persona.builtin_persona.is_(False), Persona.deleted.is_(False)
            ).label("agents"),
            total(MCPServer).label("mcp_servers"),
            total(Tool, Tool.openapi_schema.is_not(None)).label("custom_actions"),
            total(DocumentSet).label("document_sets"),
            total(SlackBot).label("slack_bots"),
            total(SSOProvider, SSOProvider.enabled.is_(True)).label("sso_providers"),
        )
    ).one()
    providers = db_session.execute(
        select(LLMProvider.provider, func.count())
        .group_by(LLMProvider.provider)
        .order_by(LLMProvider.provider)
        .limit(ROW_LIMIT)
    ).all()
    return SetupCounts(
        counts=dict(counts._mapping),
        llm_providers=[(provider, count) for provider, count in providers],
    )
