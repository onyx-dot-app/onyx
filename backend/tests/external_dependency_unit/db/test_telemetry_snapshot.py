"""Tests for the deployment snapshot that backs POC telemetry."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_CC_PAIR_ID, MessageType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    PermissionSyncStatus,
)
from onyx.db.models import (
    ChatMessage,
    ChatMessageFeedback,
    ChatSession,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    IndexAttempt,
    User,
)
from onyx.db.telemetry_snapshot import (
    ConnectorSnapshot,
    DeploymentSnapshot,
    UserSnapshot,
    build_deployment_snapshot,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    seed_cc_pair_documents,
)


def _find_user(snapshot: DeploymentSnapshot, email: str) -> UserSnapshot:
    return next(item for item in snapshot.users.items if item.email == email)


def _find_connector(snapshot: DeploymentSnapshot, cc_pair_id: int) -> ConnectorSnapshot:
    return next(
        item for item in snapshot.connectors.items if item.cc_pair_id == cc_pair_id
    )


@pytest.fixture
def cc_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    """A connector that isn't the internal user-file pair, torn down afterwards."""
    pairs = [make_cc_pair(db_session)]
    if pairs[0].id == DEFAULT_CC_PAIR_ID:
        pairs.append(make_cc_pair(db_session))
    try:
        yield pairs[-1]
    finally:
        db_session.rollback()
        # cleanup_cc_pair doesn't know about attempt rows, and their FKs block
        # the cc_pair delete
        for pair in pairs:
            for model in (
                IndexAttempt,
                DocPermissionSyncAttempt,
                ExternalGroupPermissionSyncAttempt,
            ):
                db_session.query(model).filter(
                    model.connector_credential_pair_id == pair.id
                ).delete(synchronize_session="fetch")
        db_session.commit()
        for pair in reversed(pairs):
            cleanup_cc_pair(db_session, pair)


@pytest.fixture
def chatting_user(db_session: Session) -> Generator[User, None, None]:
    """A user with two queries, one rated up and one rated down."""
    user = create_test_user(db_session, "snapshot_user")
    session = ChatSession(id=uuid4(), user_id=user.id, description="snapshot")
    db_session.add(session)
    db_session.flush()

    for i in range(2):
        db_session.add(
            ChatMessage(
                chat_session_id=session.id,
                message=f"query {i}",
                token_count=1,
                message_type=MessageType.USER,
            )
        )
    # Feedback hangs off assistant messages, not the queries themselves
    for is_positive in (True, False):
        answer = ChatMessage(
            chat_session_id=session.id,
            message="answer",
            token_count=1,
            message_type=MessageType.ASSISTANT,
        )
        db_session.add(answer)
        db_session.flush()
        db_session.add(
            ChatMessageFeedback(chat_message_id=answer.id, is_positive=is_positive)
        )
    db_session.commit()

    try:
        yield user
    finally:
        db_session.rollback()
        db_session.query(ChatMessageFeedback).filter(
            ChatMessageFeedback.chat_message_id.in_(
                db_session.query(ChatMessage.id).filter(
                    ChatMessage.chat_session_id == session.id
                )
            )
        ).delete(synchronize_session="fetch")
        db_session.query(ChatMessage).filter(
            ChatMessage.chat_session_id == session.id
        ).delete(synchronize_session="fetch")
        db_session.query(ChatSession).filter(ChatSession.id == session.id).delete()
        db_session.query(User).filter(User.__table__.c.id == user.id).delete()
        db_session.commit()


def test_snapshot_reports_onboarded_users_with_emails(
    db_session: Session,
    chatting_user: User,
    tenant_context: None,  # noqa: ARG001
) -> None:
    snapshot = build_deployment_snapshot(db_session)

    reported = _find_user(snapshot, chatting_user.email)
    assert reported.user_id == str(chatting_user.id)
    assert reported.role == chatting_user.role.value
    assert reported.is_active
    assert reported.num_queries == 2
    assert reported.last_query_at is not None

    assert snapshot.users.total >= 1
    assert snapshot.users.by_role.get(chatting_user.role.value, 0) >= 1
    assert not snapshot.users.truncated


def test_snapshot_counts_queries_and_feedback(
    db_session: Session,
    chatting_user: User,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> None:
    # These counters are deployment-wide and the DB is shared across tests, so
    # the fixture's rows are a floor rather than the exact expected value.
    snapshot = build_deployment_snapshot(db_session)

    assert snapshot.queries.total >= 2
    assert snapshot.queries.last_24h >= 2
    assert snapshot.feedback.positive >= 1
    assert snapshot.feedback.negative >= 1


def test_snapshot_reports_connector_type_docs_and_sync_status(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    tenant_context: None,  # noqa: ARG001
) -> None:
    cc_pair.access_type = AccessType.SYNC
    cc_pair.auto_sync_options = {"enabled": True}
    cc_pair.total_docs_indexed = 3
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            from_beginning=True,
            status=IndexingStatus.SUCCESS,
            new_docs_indexed=3,
            total_docs_indexed=3,
        )
    )
    db_session.add(
        DocPermissionSyncAttempt(
            connector_credential_pair_id=cc_pair.id,
            status=PermissionSyncStatus.FAILED,
            total_docs_synced=1,
            docs_with_permission_errors=2,
        )
    )
    db_session.add(
        ExternalGroupPermissionSyncAttempt(
            connector_credential_pair_id=cc_pair.id,
            status=PermissionSyncStatus.SUCCESS,
            total_users_processed=5,
            total_groups_processed=2,
        )
    )
    seed_cc_pair_documents(db_session, cc_pair, 3, prefix="snapdoc-", unique=True)
    db_session.commit()

    reported = _find_connector(build_deployment_snapshot(db_session), cc_pair.id)

    assert reported.source == cc_pair.connector.source.value
    assert reported.access_type == AccessType.SYNC.value
    assert reported.auto_sync_enabled
    assert reported.status == ConnectorCredentialPairStatus.ACTIVE.value
    assert not reported.in_repeated_error_state
    assert reported.docs_in_index == 3
    assert reported.total_docs_indexed == 3

    assert reported.last_index_attempt is not None
    assert reported.last_index_attempt.status == IndexingStatus.SUCCESS.value
    assert reported.last_index_attempt.new_docs_indexed == 3

    assert reported.last_doc_permission_sync is not None
    assert reported.last_doc_permission_sync.status == PermissionSyncStatus.FAILED.value
    assert reported.last_doc_permission_sync.docs_with_permission_errors == 2

    assert reported.last_external_group_sync is not None
    assert (
        reported.last_external_group_sync.status == PermissionSyncStatus.SUCCESS.value
    )
    assert reported.last_external_group_sync.total_groups_processed == 2


def test_snapshot_reports_latest_attempt_per_connector(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A connector that failed after succeeding should read as failed."""
    for status in (IndexingStatus.SUCCESS, IndexingStatus.FAILED):
        db_session.add(
            IndexAttempt(
                connector_credential_pair_id=cc_pair.id,
                from_beginning=True,
                status=status,
            )
        )
        db_session.commit()

    reported = _find_connector(build_deployment_snapshot(db_session), cc_pair.id)
    assert reported.last_index_attempt is not None
    assert reported.last_index_attempt.status == IndexingStatus.FAILED.value


def test_snapshot_excludes_internal_default_connector(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    snapshot = build_deployment_snapshot(db_session)
    assert all(
        item.cc_pair_id != DEFAULT_CC_PAIR_ID for item in snapshot.connectors.items
    )


def test_snapshot_is_json_serializable(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The telemetry POST json-encodes the payload, so datetimes must not survive."""
    import json

    payload = build_deployment_snapshot(db_session).model_dump(mode="json")
    assert json.loads(json.dumps(payload)) == payload
