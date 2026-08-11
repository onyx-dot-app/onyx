"""Point-in-time snapshot of a deployment's onboarding + usage state.

Answers the questions we care about while a POC is running: who has been
onboarded, which connectors exist and whether their indexing / permission
syncing is healthy, how much the deployment is being queried, and how those
answers are rated. Emitted periodically via the anonymous telemetry system, so
it works identically for self-hosted and cloud tenants.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import DEFAULT_CC_PAIR_ID, MessageType
from onyx.db.document import get_document_counts_for_all_cc_pairs
from onyx.db.models import (
    ChatMessage,
    ChatMessageFeedback,
    ChatSession,
    Connector,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    User,
)
from onyx.db.users import (
    get_accepted_user_where_clause,
    get_user_counts_by_role_and_status,
)

# Keep a single telemetry POST bounded on large deployments. A POC sits far
# below both caps, so in practice nothing is ever dropped.
MAX_USERS_REPORTED = 1000
MAX_CONNECTORS_REPORTED = 500


class UserSnapshot(BaseModel):
    user_id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime | None
    num_queries: int
    last_query_at: datetime | None


class UsersSection(BaseModel):
    total: int
    active: int
    by_role: dict[str, int]
    # Users discovered by permission sync rather than onboarded; counted only.
    external_permission_users: int
    truncated: bool
    items: list[UserSnapshot]


class AttemptSnapshot(BaseModel):
    status: str
    time_started: datetime | None
    time_finished: datetime | None


class IndexAttemptSnapshot(AttemptSnapshot):
    new_docs_indexed: int
    total_docs_indexed: int


class DocPermissionSyncSnapshot(AttemptSnapshot):
    total_docs_synced: int
    docs_with_permission_errors: int


class ExternalGroupSyncSnapshot(AttemptSnapshot):
    total_users_processed: int
    total_groups_processed: int


class ConnectorSnapshot(BaseModel):
    cc_pair_id: int
    source: str
    # Permission mode: public / private / sync
    access_type: str
    auto_sync_enabled: bool
    status: str
    in_repeated_error_state: bool
    # Documents currently attributed to this connector in the index
    docs_in_index: int
    # Running total the connector itself reports having indexed
    total_docs_indexed: int
    last_index_attempt: IndexAttemptSnapshot | None
    last_doc_permission_sync: DocPermissionSyncSnapshot | None
    last_external_group_sync: ExternalGroupSyncSnapshot | None


class ConnectorsSection(BaseModel):
    total: int
    truncated: bool
    items: list[ConnectorSnapshot]


class QueriesSection(BaseModel):
    total: int
    last_24h: int


class FeedbackSection(BaseModel):
    positive: int
    negative: int
    unrated: int


class DeploymentSnapshot(BaseModel):
    snapshot_at: datetime
    users: UsersSection
    connectors: ConnectorsSection
    queries: QueriesSection
    feedback: FeedbackSection


class _UserQueryStats(BaseModel):
    num_queries: int
    last_query_at: datetime | None


def _query_stats_by_user(db_session: Session) -> dict[UUID, _UserQueryStats]:
    """Query counts keyed by user. Sessions with no owner (Slack/anonymous flows)
    are excluded here but still counted in the deployment-wide total."""
    return {
        user_id: _UserQueryStats(num_queries=num_queries, last_query_at=last_query_at)
        for user_id, num_queries, last_query_at in db_session.execute(
            select(
                ChatSession.user_id,
                func.count(ChatMessage.id),
                func.max(ChatMessage.time_sent),
            )
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(ChatMessage.message_type == MessageType.USER)
            .group_by(ChatSession.user_id)
        )
        if user_id is not None
    }


def _collect_users(db_session: Session) -> UsersSection:
    query_stats = _query_stats_by_user(db_session)

    counts = get_user_counts_by_role_and_status(db_session)
    by_role = counts["role_counts"]

    external_permission_users = db_session.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.EXT_PERM_USER)
    ).scalar_one()

    # `id` / `email` / `is_active` come from the fastapi-users base class, so go
    # through __table__.c to get properly typed SQLAlchemy columns.
    # One extra row tells us whether the cap truncated the list.
    rows = db_session.execute(
        select(
            User.__table__.c.id,
            User.__table__.c.email,
            User.role,
            User.__table__.c.is_active,
            User.created_at,
        )
        .where(*get_accepted_user_where_clause())
        .order_by(User.created_at, User.__table__.c.id)
        .limit(MAX_USERS_REPORTED + 1)
    ).all()
    truncated = len(rows) > MAX_USERS_REPORTED

    no_queries = _UserQueryStats(num_queries=0, last_query_at=None)
    items = [
        UserSnapshot(
            user_id=str(user_id),
            email=email,
            role=role.value,
            is_active=is_active,
            created_at=created_at,
            num_queries=query_stats.get(user_id, no_queries).num_queries,
            last_query_at=query_stats.get(user_id, no_queries).last_query_at,
        )
        for user_id, email, role, is_active, created_at in rows[:MAX_USERS_REPORTED]
    ]

    return UsersSection(
        total=sum(by_role.values()),
        active=counts["status_counts"]["active"],
        by_role=by_role,
        external_permission_users=external_permission_users,
        truncated=truncated,
        items=items,
    )


def _latest_index_attempts(
    db_session: Session, cc_pair_ids: list[int]
) -> dict[int, IndexAttemptSnapshot]:
    """Latest full-run attempt per cc_pair in one DISTINCT ON pass. Targeted
    reindexes and synthetic seed rows aren't connector runs, so they're skipped."""
    if not cc_pair_ids:
        return {}

    return {
        cc_pair_id: IndexAttemptSnapshot(
            status=status.value,
            time_started=time_started,
            time_finished=time_updated if status.is_terminal() else None,
            new_docs_indexed=new_docs_indexed or 0,
            total_docs_indexed=total_docs_indexed or 0,
        )
        for (
            cc_pair_id,
            status,
            time_started,
            time_updated,
            new_docs_indexed,
            total_docs_indexed,
        ) in db_session.execute(
            select(
                IndexAttempt.connector_credential_pair_id,
                IndexAttempt.status,
                IndexAttempt.time_started,
                IndexAttempt.time_updated,
                IndexAttempt.new_docs_indexed,
                IndexAttempt.total_docs_indexed,
            )
            .where(
                IndexAttempt.connector_credential_pair_id.in_(cc_pair_ids),
                IndexAttempt.targeted_reindex_job_id.is_(None),
                IndexAttempt.is_synthetic_seed.is_(False),
            )
            .distinct(IndexAttempt.connector_credential_pair_id)
            .order_by(
                IndexAttempt.connector_credential_pair_id,
                IndexAttempt.time_created.desc(),
                IndexAttempt.id.desc(),
            )
        )
    }


def _latest_doc_permission_syncs(
    db_session: Session, cc_pair_ids: list[int]
) -> dict[int, DocPermissionSyncSnapshot]:
    if not cc_pair_ids:
        return {}

    return {
        cc_pair_id: DocPermissionSyncSnapshot(
            status=status.value,
            time_started=time_started,
            time_finished=time_finished,
            total_docs_synced=total_docs_synced or 0,
            docs_with_permission_errors=docs_with_permission_errors or 0,
        )
        for (
            cc_pair_id,
            status,
            time_started,
            time_finished,
            total_docs_synced,
            docs_with_permission_errors,
        ) in db_session.execute(
            select(
                DocPermissionSyncAttempt.connector_credential_pair_id,
                DocPermissionSyncAttempt.status,
                DocPermissionSyncAttempt.time_started,
                DocPermissionSyncAttempt.time_finished,
                DocPermissionSyncAttempt.total_docs_synced,
                DocPermissionSyncAttempt.docs_with_permission_errors,
            )
            .where(
                DocPermissionSyncAttempt.connector_credential_pair_id.in_(cc_pair_ids)
            )
            .distinct(DocPermissionSyncAttempt.connector_credential_pair_id)
            .order_by(
                DocPermissionSyncAttempt.connector_credential_pair_id,
                DocPermissionSyncAttempt.time_created.desc(),
                DocPermissionSyncAttempt.id.desc(),
            )
        )
    }


def _latest_external_group_syncs(
    db_session: Session, cc_pair_ids: list[int]
) -> dict[int, ExternalGroupSyncSnapshot]:
    if not cc_pair_ids:
        return {}

    return {
        cc_pair_id: ExternalGroupSyncSnapshot(
            status=status.value,
            time_started=time_started,
            time_finished=time_finished,
            total_users_processed=total_users_processed or 0,
            total_groups_processed=total_groups_processed or 0,
        )
        for (
            cc_pair_id,
            status,
            time_started,
            time_finished,
            total_users_processed,
            total_groups_processed,
        ) in db_session.execute(
            select(
                ExternalGroupPermissionSyncAttempt.connector_credential_pair_id,
                ExternalGroupPermissionSyncAttempt.status,
                ExternalGroupPermissionSyncAttempt.time_started,
                ExternalGroupPermissionSyncAttempt.time_finished,
                ExternalGroupPermissionSyncAttempt.total_users_processed,
                ExternalGroupPermissionSyncAttempt.total_groups_processed,
            )
            .where(
                ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(
                    cc_pair_ids
                )
            )
            .distinct(ExternalGroupPermissionSyncAttempt.connector_credential_pair_id)
            .order_by(
                ExternalGroupPermissionSyncAttempt.connector_credential_pair_id,
                ExternalGroupPermissionSyncAttempt.time_created.desc(),
                ExternalGroupPermissionSyncAttempt.id.desc(),
            )
        )
        if cc_pair_id is not None
    }


def _collect_connectors(db_session: Session) -> ConnectorsSection:
    # DEFAULT_CC_PAIR_ID is the internal user-file/ingestion pair, not a connector
    # anyone set up, so it's excluded from both the count and the listing.
    total = db_session.execute(
        select(func.count())
        .select_from(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.id != DEFAULT_CC_PAIR_ID)
    ).scalar_one()

    rows = db_session.execute(
        select(
            ConnectorCredentialPair.id,
            ConnectorCredentialPair.connector_id,
            ConnectorCredentialPair.credential_id,
            ConnectorCredentialPair.status,
            ConnectorCredentialPair.access_type,
            ConnectorCredentialPair.auto_sync_options,
            ConnectorCredentialPair.in_repeated_error_state,
            ConnectorCredentialPair.total_docs_indexed,
            Connector.source,
        )
        .join(Connector, Connector.id == ConnectorCredentialPair.connector_id)
        .where(ConnectorCredentialPair.id != DEFAULT_CC_PAIR_ID)
        .order_by(ConnectorCredentialPair.id)
        .limit(MAX_CONNECTORS_REPORTED)
    ).all()

    cc_pair_ids = [row[0] for row in rows]
    index_attempts = _latest_index_attempts(db_session, cc_pair_ids)
    permission_syncs = _latest_doc_permission_syncs(db_session, cc_pair_ids)
    group_syncs = _latest_external_group_syncs(db_session, cc_pair_ids)
    docs_in_index = {
        (connector_id, credential_id): count
        for connector_id, credential_id, count in get_document_counts_for_all_cc_pairs(
            db_session
        )
    }

    items = [
        ConnectorSnapshot(
            cc_pair_id=cc_pair_id,
            source=source.value,
            access_type=access_type.value,
            auto_sync_enabled=bool(auto_sync_options),
            status=status.value,
            in_repeated_error_state=in_repeated_error_state,
            docs_in_index=docs_in_index.get((connector_id, credential_id), 0),
            total_docs_indexed=total_docs_indexed or 0,
            last_index_attempt=index_attempts.get(cc_pair_id),
            last_doc_permission_sync=permission_syncs.get(cc_pair_id),
            last_external_group_sync=group_syncs.get(cc_pair_id),
        )
        for (
            cc_pair_id,
            connector_id,
            credential_id,
            status,
            access_type,
            auto_sync_options,
            in_repeated_error_state,
            total_docs_indexed,
            source,
        ) in rows
    ]

    return ConnectorsSection(
        total=total,
        truncated=total > len(items),
        items=items,
    )


def _collect_queries(db_session: Session, now: datetime) -> QueriesSection:
    total, last_24h = db_session.execute(
        select(
            func.count(ChatMessage.id),
            func.count(ChatMessage.id).filter(
                ChatMessage.time_sent >= now - timedelta(days=1)
            ),
        ).where(ChatMessage.message_type == MessageType.USER)
    ).one()

    return QueriesSection(total=total, last_24h=last_24h)


def _collect_feedback(db_session: Session) -> FeedbackSection:
    counts = {
        is_positive: count
        for is_positive, count in db_session.execute(
            select(ChatMessageFeedback.is_positive, func.count()).group_by(
                ChatMessageFeedback.is_positive
            )
        )
    }

    return FeedbackSection(
        positive=counts.get(True, 0),
        negative=counts.get(False, 0),
        unrated=counts.get(None, 0),
    )


def build_deployment_snapshot(db_session: Session) -> DeploymentSnapshot:
    now = datetime.now(timezone.utc)
    return DeploymentSnapshot(
        snapshot_at=now,
        users=_collect_users(db_session),
        connectors=_collect_connectors(db_session),
        queries=_collect_queries(db_session, now),
        feedback=_collect_feedback(db_session),
    )
