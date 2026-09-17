"""External-dependency-unit tests for the artifact and receipt DALs.

Runs real ORM/SQL against Postgres so the upsert semantics the reconciler
depends on (hash-driven version bumps, archive invalidation, operation-key
coalescing, terminal receipt states) actually fail on regression.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ArtifactType, ReceiptStatus
from onyx.db.models import ActionReceipt, Artifact, BuildSession
from onyx.server.features.build.db.artifact import (
    get_session_artifacts,
    mark_artifact_deleted,
    upsert_artifact,
)
from onyx.server.features.build.db.receipt import (
    finalize_receipt,
    get_session_receipts,
    insert_pending_receipt,
    sweep_stale_pending_receipts,
)
from tests.external_dependency_unit.craft.db_helpers import force_receipt_created_at


def _upsert(
    db_session: Session,
    session: BuildSession,
    *,
    path: str = "q3_board_deck.pptx",
    content_hash: str | None = "hash-a",
    turn_index: int | None = 1,
) -> Artifact:
    return upsert_artifact(
        db_session,
        session_id=session.id,
        artifact_type=ArtifactType.PPTX,
        path=path,
        name=path,
        turn_index=turn_index,
        size_bytes=1024,
        content_hash=content_hash,
    )


def test_upsert_same_hash_touches_without_version_bump(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    first = _upsert(db_session, session)
    db_session.commit()
    assert first.version == 1

    second = _upsert(db_session, session, turn_index=2)
    db_session.commit()
    assert second.id == first.id
    assert second.version == 1
    assert second.turn_index == 2


def test_upsert_content_change_bumps_version_and_clears_archive(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    first = _upsert(db_session, session)
    first.archive_file_id = "file-store-id"
    db_session.commit()

    second = _upsert(db_session, session, content_hash="hash-b")
    db_session.commit()
    assert second.id == first.id
    assert second.version == 2
    assert second.archive_file_id is None


def test_deleted_artifact_hidden_then_resurrected(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    _upsert(db_session, session)
    db_session.commit()

    deleted = mark_artifact_deleted(
        db_session, session_id=session.id, path="q3_board_deck.pptx"
    )
    db_session.commit()
    assert deleted is not None and deleted.deleted

    assert get_session_artifacts(db_session, session_id=session.id) == []
    assert (
        len(
            get_session_artifacts(
                db_session, session_id=session.id, include_deleted=True
            )
        )
        == 1
    )

    resurrected = _upsert(db_session, session, turn_index=3)
    db_session.commit()
    assert not resurrected.deleted
    assert len(get_session_artifacts(db_session, session_id=session.id)) == 1


def test_same_path_isolated_per_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session_a = build_session_with_user()
    session_b = build_session_with_user()
    _upsert(db_session, session_a)
    _upsert(db_session, session_b)
    db_session.commit()

    assert len(get_session_artifacts(db_session, session_id=session_a.id)) == 1
    assert len(get_session_artifacts(db_session, session_id=session_b.id)) == 1


def _pending(
    db_session: Session,
    session: BuildSession,
    *,
    operation_key: str | None = None,
    action_type: str = "slack.messages.write",
) -> ActionReceipt:
    return insert_pending_receipt(
        db_session,
        session_id=session.id,
        action_type=action_type,
        effect="write",
        destination="#exec-team",
        gated_app_id=None,
        approval_id=None,
        operation_key=operation_key,
    )


def test_pending_receipt_coalesces_on_operation_key(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    first = _pending(db_session, session, operation_key="upload-1")
    second = _pending(db_session, session, operation_key="upload-1")
    third = _pending(db_session, session, operation_key="upload-2")
    db_session.commit()

    assert second.id == first.id
    assert third.id != first.id
    assert len(get_session_receipts(db_session, session_id=session.id)) == 2


def test_finalize_is_terminal_and_rejects_pending(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    receipt = _pending(db_session, session)
    db_session.commit()

    confirmed = finalize_receipt(
        db_session,
        receipt_id=receipt.id,
        status=ReceiptStatus.CONFIRMED,
        link="https://slack.com/archives/C1/p1",
    )
    db_session.commit()
    assert confirmed is not None
    assert confirmed.status == ReceiptStatus.CONFIRMED
    assert confirmed.link is not None

    flipped = finalize_receipt(
        db_session, receipt_id=receipt.id, status=ReceiptStatus.FAILED
    )
    db_session.commit()
    assert flipped is not None
    assert flipped.status == ReceiptStatus.CONFIRMED

    for non_terminal in (ReceiptStatus.PENDING, ReceiptStatus.UNKNOWN):
        with pytest.raises(ValueError):
            finalize_receipt(db_session, receipt_id=receipt.id, status=non_terminal)


def test_sweep_marks_only_stale_pending_unknown(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    session = build_session_with_user()
    stale = _pending(db_session, session, action_type="drive.files.upload")
    fresh = _pending(db_session, session)
    db_session.commit()

    force_receipt_created_at(
        db_session, stale.id, datetime.now(tz=timezone.utc) - timedelta(hours=1)
    )

    swept = sweep_stale_pending_receipts(db_session)
    db_session.commit()
    assert swept == 1
    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert stale.status == ReceiptStatus.UNKNOWN
    assert fresh.status == ReceiptStatus.PENDING

    confirmed_only = get_session_receipts(
        db_session, session_id=session.id, statuses=[ReceiptStatus.CONFIRMED]
    )
    assert confirmed_only == []
