"""The access change the connector-edit apply step makes, and the mark of a
pair awaiting its first permission sync. Entering a perm-synced type from
another type makes both syncs due and sets the mark; leaving one clears it;
SYNC <-> SYNC_RESTRICTED keeps it. The mark clears only after a doc permission
sync that started after it succeeds, the external group sync too when the
source has one, and the metadata sync of the pair's documents catches up."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing.tasks import (
    clear_caught_up_perm_sync_pending_marks,
    is_external_doc_permissions_sync_due,
)
from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    is_external_group_sync_due,
)
from ee.onyx.db.connector_credential_pair import clear_perm_sync_pending__no_commit
from onyx.configs.constants import DocumentSource
from onyx.db.connector import mark_cc_pair_as_permissions_synced
from onyx.db.connector_edit_requests import apply_access_change__no_commit
from onyx.db.document import (
    mark_cc_pair_documents_for_sync__no_commit,
    mark_document_as_synced,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    UserGroup,
    UserGroup__CCPairDataAccess,
)
from onyx.db.models import Document as DbDocument
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.db.agent_sharing_helpers import (
    create_test_user_group,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_EARLIER = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _PairFactory(Protocol):
    def __call__(
        self,
        access_type: AccessType,
        source: DocumentSource = DocumentSource.MOCK_CONNECTOR,
    ) -> ConnectorCredentialPair: ...


@pytest.fixture(autouse=True)
def ee(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: True)
    yield
    fetch_versioned_implementation.cache_clear()


@pytest.fixture
def groups(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[UserGroup], None, None]:
    created = [create_test_user_group(db_session, members=[]) for _ in range(2)]
    try:
        yield created
    finally:
        db_session.rollback()
        group_ids = [group.id for group in created]
        db_session.execute(
            delete(UserGroup__CCPairDataAccess).where(
                UserGroup__CCPairDataAccess.user_group_id.in_(group_ids)
            )
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id.in_(group_ids)))
        db_session.commit()


def _make_pair(
    db_session: Session,
    access_type: AccessType,
    source: DocumentSource = DocumentSource.MOCK_CONNECTOR,
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session, source)
    pair.access_type = access_type
    pair.last_time_perm_sync = _EARLIER
    pair.last_time_external_group_sync = _EARLIER
    db_session.commit()
    return pair


@pytest.fixture
def make_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_PairFactory, None, None]:
    pairs: list[ConnectorCredentialPair] = []

    def _make(
        access_type: AccessType,
        source: DocumentSource = DocumentSource.MOCK_CONNECTOR,
    ) -> ConnectorCredentialPair:
        pair = _make_pair(db_session, access_type, source)
        pairs.append(pair)
        return pair

    try:
        yield _make
    finally:
        db_session.rollback()
        for pair in pairs:
            db_session.execute(
                delete(UserGroup__CCPairDataAccess).where(
                    UserGroup__CCPairDataAccess.cc_pair_id == pair.id
                )
            )
            db_session.commit()
            cleanup_cc_pair(db_session, pair)


def _add_synced_document(db_session: Session, pair: ConnectorCredentialPair) -> str:
    doc_id = f"access-transition-{uuid4().hex[:8]}"
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            chunk_count=1,
            last_modified=_EARLIER,
            last_synced=_EARLIER,
        )
    )
    db_session.commit()
    upsert_document_by_connector_credential_pair(
        db_session, pair.connector_id, pair.credential_id, [doc_id]
    )
    return doc_id


def _needs_metadata_sync(db_session: Session, doc_id: str) -> bool:
    doc = db_session.get(DbDocument, doc_id)
    assert doc is not None
    db_session.refresh(doc)
    assert doc.last_modified is not None and doc.last_synced is not None
    return doc.last_modified > doc.last_synced


def _data_access_group_ids(db_session: Session, pair_id: int) -> set[int]:
    return set(
        db_session.scalars(
            select(UserGroup__CCPairDataAccess.user_group_id).where(
                UserGroup__CCPairDataAccess.cc_pair_id == pair_id
            )
        )
    )


def _change(
    db_session: Session,
    pair: ConnectorCredentialPair,
    access_type: AccessType,
    data_access_group_ids: set[int] | None = None,
) -> None:
    apply_access_change__no_commit(
        db_session,
        pair.id,
        access_type,
        data_access_group_ids=data_access_group_ids or set(),
        visible_group_ids=None,
    )
    db_session.commit()
    db_session.refresh(pair)


@pytest.mark.parametrize("from_type", [AccessType.PUBLIC, AccessType.PRIVATE])
@pytest.mark.parametrize("to_type", [AccessType.SYNC, AccessType.SYNC_RESTRICTED])
def test_entering_perm_sync_makes_syncs_due_and_sets_the_mark(
    db_session: Session,
    make_pair: _PairFactory,
    groups: list[UserGroup],
    from_type: AccessType,
    to_type: AccessType,
) -> None:
    pair = make_pair(from_type)
    if from_type == AccessType.PRIVATE:
        db_session.add(
            UserGroup__CCPairDataAccess(user_group_id=groups[0].id, cc_pair_id=pair.id)
        )
        db_session.commit()
    doc_id = _add_synced_document(db_session, pair)
    new_group_ids = (
        {groups[1].id} if to_type == AccessType.SYNC_RESTRICTED else set[int]()
    )

    _change(db_session, pair, to_type, new_group_ids)

    assert pair.access_type == to_type
    assert pair.last_time_perm_sync is None
    assert pair.last_time_external_group_sync is None
    assert pair.perm_sync_pending_since is not None
    assert _data_access_group_ids(db_session, pair.id) == new_group_ids
    assert _needs_metadata_sync(db_session, doc_id)


@pytest.mark.parametrize("to_type", [AccessType.PUBLIC, AccessType.PRIVATE])
def test_leaving_perm_sync_clears_the_mark_and_keeps_the_sync_times(
    db_session: Session,
    make_pair: _PairFactory,
    groups: list[UserGroup],
    to_type: AccessType,
) -> None:
    pair = make_pair(AccessType.PUBLIC)
    _change(db_session, pair, AccessType.SYNC)
    assert pair.perm_sync_pending_since is not None
    pair.last_time_perm_sync = _EARLIER
    db_session.commit()
    new_group_ids = {groups[0].id} if to_type == AccessType.PRIVATE else set[int]()

    _change(db_session, pair, to_type, new_group_ids)

    assert pair.access_type == to_type
    assert pair.perm_sync_pending_since is None
    assert pair.last_time_perm_sync == _EARLIER
    assert _data_access_group_ids(db_session, pair.id) == new_group_ids


def test_sync_and_sync_restricted_keep_the_mark_as_it_is(
    db_session: Session, make_pair: _PairFactory, groups: list[UserGroup]
) -> None:
    synced_pair = make_pair(AccessType.SYNC)
    doc_id = _add_synced_document(db_session, synced_pair)
    _change(
        db_session,
        synced_pair,
        AccessType.SYNC_RESTRICTED,
        {groups[0].id, groups[1].id},
    )
    assert synced_pair.perm_sync_pending_since is None
    assert synced_pair.last_time_perm_sync == _EARLIER
    assert _data_access_group_ids(db_session, synced_pair.id) == {
        groups[0].id,
        groups[1].id,
    }
    assert _needs_metadata_sync(db_session, doc_id)

    _change(db_session, synced_pair, AccessType.SYNC)
    assert synced_pair.perm_sync_pending_since is None
    assert _data_access_group_ids(db_session, synced_pair.id) == set()

    pending_pair = make_pair(AccessType.PUBLIC)
    _change(db_session, pending_pair, AccessType.SYNC)
    pending_since = pending_pair.perm_sync_pending_since
    assert pending_since is not None
    _change(db_session, pending_pair, AccessType.SYNC_RESTRICTED, {groups[0].id})
    assert pending_pair.perm_sync_pending_since == pending_since


def test_public_and_private_switch_without_the_mark(
    db_session: Session, make_pair: _PairFactory, groups: list[UserGroup]
) -> None:
    pair = make_pair(AccessType.PUBLIC)
    doc_id = _add_synced_document(db_session, pair)

    _change(db_session, pair, AccessType.PRIVATE, {groups[0].id})
    assert pair.perm_sync_pending_since is None
    assert pair.last_time_perm_sync == _EARLIER
    assert _data_access_group_ids(db_session, pair.id) == {groups[0].id}
    assert _needs_metadata_sync(db_session, doc_id)

    # Same type and groups: no document is marked again.
    mark_document_as_synced(doc_id, db_session)
    _change(db_session, pair, AccessType.PRIVATE, {groups[0].id})
    assert not _needs_metadata_sync(db_session, doc_id)


def test_access_change_rejects_bad_groups(
    db_session: Session, make_pair: _PairFactory, groups: list[UserGroup]
) -> None:
    pair = make_pair(AccessType.SYNC)
    with pytest.raises(OnyxError) as exc_info:
        _change(db_session, pair, AccessType.SYNC_RESTRICTED)
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    db_session.rollback()

    with pytest.raises(ValueError):
        _change(db_session, pair, AccessType.PUBLIC, {groups[0].id})


def _pending_pair(
    db_session: Session,
    make_pair: _PairFactory,
    source: DocumentSource = DocumentSource.MOCK_CONNECTOR,
) -> tuple[ConnectorCredentialPair, str]:
    pair = make_pair(AccessType.PUBLIC, source)
    doc_id = _add_synced_document(db_session, pair)
    _change(db_session, pair, AccessType.SYNC)
    assert pair.perm_sync_pending_since is not None
    return pair, doc_id


def _clear(db_session: Session, pair: ConnectorCredentialPair) -> bool:
    cleared = clear_perm_sync_pending__no_commit(
        db_session, pair.id, needs_doc_sync=True, needs_group_sync=False
    )
    db_session.commit()
    db_session.refresh(pair)
    return cleared


def test_mark_clears_after_a_later_perm_sync_and_metadata_sync(
    db_session: Session, make_pair: _PairFactory
) -> None:
    pair, doc_id = _pending_pair(db_session, make_pair)
    pending_since = pair.perm_sync_pending_since
    assert pending_since is not None

    # No perm sync yet, or a failed one: last_time_perm_sync stays NULL.
    assert not _clear(db_session, pair)

    # A sync that started before the mark does not count.
    mark_cc_pair_as_permissions_synced(
        db_session, pair.id, pending_since - timedelta(seconds=1)
    )
    assert not _clear(db_session, pair)

    # A later sync, but the chunks still carry the old access.
    mark_cc_pair_as_permissions_synced(
        db_session, pair.id, pending_since + timedelta(seconds=1)
    )
    assert _needs_metadata_sync(db_session, doc_id)
    assert not _clear(db_session, pair)
    assert pair.perm_sync_pending_since == pending_since

    mark_document_as_synced(doc_id, db_session)
    assert _clear(db_session, pair)
    assert pair.perm_sync_pending_since is None
    assert not _clear(db_session, pair)


def test_beat_waits_for_group_sync_when_the_source_has_one(
    db_session: Session, make_pair: _PairFactory
) -> None:
    pair, doc_id = _pending_pair(db_session, make_pair, DocumentSource.GOOGLE_DRIVE)
    pending_since = pair.perm_sync_pending_since
    assert pending_since is not None
    mark_cc_pair_as_permissions_synced(
        db_session, pair.id, pending_since + timedelta(seconds=1)
    )
    mark_document_as_synced(doc_id, db_session)

    clear_caught_up_perm_sync_pending_marks(get_current_tenant_id())
    db_session.refresh(pair)
    assert pair.perm_sync_pending_since == pending_since

    pair.last_time_external_group_sync = pending_since + timedelta(seconds=1)
    db_session.commit()
    clear_caught_up_perm_sync_pending_marks(get_current_tenant_id())
    db_session.refresh(pair)
    assert pair.perm_sync_pending_since is None


def test_beat_clears_without_group_sync_for_a_source_without_one(
    db_session: Session, make_pair: _PairFactory
) -> None:
    pair, doc_id = _pending_pair(db_session, make_pair, DocumentSource.SLACK)
    pending_since = pair.perm_sync_pending_since
    assert pending_since is not None
    mark_cc_pair_as_permissions_synced(
        db_session, pair.id, pending_since + timedelta(seconds=1)
    )
    mark_document_as_synced(doc_id, db_session)

    clear_caught_up_perm_sync_pending_marks(get_current_tenant_id())
    db_session.refresh(pair)
    assert pair.perm_sync_pending_since is None


def test_syncs_that_started_before_the_mark_stay_due(
    db_session: Session, make_pair: _PairFactory
) -> None:
    pair, _ = _pending_pair(db_session, make_pair, DocumentSource.GOOGLE_DRIVE)
    pending_since = pair.perm_sync_pending_since
    assert pending_since is not None
    pair.status = ConnectorCredentialPairStatus.ACTIVE
    pair.last_successful_index_time = _EARLIER
    # Syncs that were running at the access change finish after it.
    pair.last_time_perm_sync = pending_since - timedelta(seconds=1)
    pair.last_time_external_group_sync = pending_since - timedelta(seconds=1)
    db_session.commit()
    assert is_external_doc_permissions_sync_due(pair)
    assert is_external_group_sync_due(pair)

    pair.last_time_perm_sync = pending_since + timedelta(seconds=1)
    pair.last_time_external_group_sync = pending_since + timedelta(seconds=1)
    db_session.commit()
    assert not is_external_doc_permissions_sync_due(pair)
    assert not is_external_group_sync_due(pair)


def test_a_source_without_doc_sync_gets_no_mark(
    db_session: Session, make_pair: _PairFactory
) -> None:
    # Salesforce checks access after search; no doc permission sync clears a
    # mark.
    salesforce_pair = make_pair(AccessType.PUBLIC, DocumentSource.SALESFORCE)
    _change(db_session, salesforce_pair, AccessType.SYNC)
    assert salesforce_pair.perm_sync_pending_since is None
    assert salesforce_pair.last_time_perm_sync is None

    drive_pair = make_pair(AccessType.PUBLIC, DocumentSource.GOOGLE_DRIVE)
    _change(db_session, drive_pair, AccessType.SYNC)
    assert drive_pair.perm_sync_pending_since is not None


def test_beat_clears_a_stale_mark_on_a_source_without_doc_sync(
    db_session: Session, make_pair: _PairFactory
) -> None:
    pair = make_pair(AccessType.SYNC, DocumentSource.SALESFORCE)
    doc_id = _add_synced_document(db_session, pair)
    # A mark that older code set, with no perm sync and a document that waits
    # for metadata sync.
    pair.perm_sync_pending_since = datetime.now(tz=timezone.utc)
    pair.last_time_perm_sync = None
    db_session.commit()
    mark_cc_pair_documents_for_sync__no_commit(db_session, [pair.id])
    db_session.commit()
    assert _needs_metadata_sync(db_session, doc_id)

    clear_caught_up_perm_sync_pending_marks(get_current_tenant_id())
    db_session.refresh(pair)
    assert pair.perm_sync_pending_since is None
