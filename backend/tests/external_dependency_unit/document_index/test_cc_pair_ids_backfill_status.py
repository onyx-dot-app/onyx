"""The admin status of the cc_pair_ids backfill: connector and document
progress computed from the stored progress and the current Postgres rows."""

from collections.abc import Generator
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.configs.constants import ONYX_CLOUD_REDIS_RUNTIME
from onyx.context.search.models import CCPairAccessMode
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.document_index.opensearch import cc_pair_ids_backfill
from onyx.document_index.opensearch.cc_pair_ids_backfill import (
    CCPairIdsBackfillProgress,
    store_cc_pair_ids_backfill_progress,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import search_settings as search_settings_api
from onyx.server.manage.models import (
    CCPairAccessModeUpdateRequest,
    CCPairIdsBackfillStatus,
)
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_SEARCH_SETTINGS = SimpleNamespace(id=1, index_name="test_backfill_status_index")
_FLAG_KEYS = [
    f"{ONYX_CLOUD_REDIS_RUNTIME}:cc_pair_access_filter:{axis}"
    for axis in ("enabled", "enforce")
]


@pytest.fixture
def flags_restored(
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Keeps the developer's cc-pair access filter flags unchanged."""
    cache = OnyxRuntime._request_path_flag_cache()
    saved = {key: cache.get(key) for key in _FLAG_KEYS}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                cache.delete(key)
            else:
                cache.set(key, value)


class _Pairs(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    done: ConnectorCredentialPair
    current: ConnectorCredentialPair
    # Documents of the current pair, in ID order.
    current_doc_ids: list[str]


@pytest.fixture
def pairs(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Pairs, None, None]:
    """The done pair has 2 documents, the current pair 3. One is shared."""
    done = make_cc_pair(db_session)
    current = make_cc_pair(db_session)
    prefix = f"backfill-status-{uuid4().hex[:8]}"
    doc_ids = {name: f"{prefix}-{name}" for name in ("a", "b", "c", "d")}
    for doc_id in doc_ids.values():
        db_session.add(DbDocument(id=doc_id, semantic_id=doc_id, chunk_count=1))
    db_session.commit()
    for pair, names in ((done, "ab"), (current, "acd")):
        upsert_document_by_connector_credential_pair(
            db_session,
            pair.connector_id,
            pair.credential_id,
            [doc_ids[name] for name in names],
        )
    try:
        yield _Pairs(
            done=done,
            current=current,
            current_doc_ids=[doc_ids[name] for name in "acd"],
        )
    finally:
        db_session.rollback()
        for pair in (done, current):
            cleanup_cc_pair(db_session, pair)


def _settings_patches() -> ExitStack:
    stack = ExitStack()
    for module in (search_settings_api, cc_pair_ids_backfill):
        stack.enter_context(
            patch.object(
                module, "get_current_search_settings", return_value=_SEARCH_SETTINGS
            )
        )
    return stack


def _set_mode(db_session: Session, mode: CCPairAccessMode) -> CCPairIdsBackfillStatus:
    with _settings_patches():
        return search_settings_api.update_cc_pair_access_mode(
            CCPairAccessModeUpdateRequest(mode=mode),
            user=MagicMock(),
            db_session=db_session,
        )


def _status(db_session: Session) -> CCPairIdsBackfillStatus:
    with (
        patch.object(
            search_settings_api,
            "get_current_search_settings",
            return_value=_SEARCH_SETTINGS,
        ),
        patch.object(
            cc_pair_ids_backfill,
            "get_current_search_settings",
            return_value=_SEARCH_SETTINGS,
        ),
    ):
        return search_settings_api.get_cc_pair_ids_backfill_status(
            _=MagicMock(), db_session=db_session
        )


def _store(
    pending: list[int] | None,
    snapshot: list[int] | None = None,
    cursor: str | None = None,
) -> None:
    store_cc_pair_ids_backfill_progress(
        CCPairIdsBackfillProgress(
            search_settings_id=_SEARCH_SETTINGS.id,
            index_name=_SEARCH_SETTINGS.index_name,
            pending_cc_pair_ids=pending,
            snapshot_cc_pair_ids=snapshot,
            last_document_id=cursor,
        )
    )


@pytest.mark.usefixtures("kv_progress_restored")
def test_status_reports_connector_and_document_progress(
    db_session: Session, pairs: _Pairs
) -> None:
    # The cursor is past 2 of the current pair's 3 documents.
    _store(
        pending=[pairs.current.id],
        snapshot=[pairs.done.id, pairs.current.id],
        cursor=pairs.current_doc_ids[1],
    )

    status = _status(db_session)

    assert status.started and not status.completed
    assert status.total_cc_pairs == 2
    assert status.pending_cc_pairs == 1
    assert status.total_documents == 5
    assert status.remaining_documents == 1
    assert status.completed_documents == 4
    assert status.current_cc_pair_name == pairs.current.name


@pytest.mark.usefixtures("kv_progress_restored")
def test_status_without_a_snapshot_reports_only_what_is_left(
    db_session: Session, pairs: _Pairs
) -> None:
    _store(pending=[pairs.current.id])

    status = _status(db_session)

    assert status.pending_cc_pairs == 1
    assert status.remaining_documents == 3
    assert status.total_cc_pairs is None
    assert status.total_documents is None
    assert status.completed_documents is None


@pytest.mark.usefixtures("kv_progress_restored", "tenant_context")
def test_status_before_start_and_after_completion(db_session: Session) -> None:
    _store(pending=None)
    status = _status(db_session)
    assert not status.started and not status.completed
    assert status.access_mode == CCPairAccessMode.OFF

    _store(pending=[], snapshot=[1, 2])
    status = _status(db_session)
    assert status.started and status.completed
    assert status.remaining_documents is None


@pytest.mark.usefixtures("kv_progress_restored", "flags_restored")
def test_mode_update_sets_both_flags(db_session: Session) -> None:
    _store(pending=[], snapshot=[1])

    for mode, enabled, enforce in (
        (CCPairAccessMode.ENFORCE, True, True),
        (CCPairAccessMode.SHADOW, True, False),
        (CCPairAccessMode.OFF, False, False),
    ):
        status = _set_mode(db_session, mode)
        assert status.access_mode == mode
        assert OnyxRuntime.get_cc_pair_access_filter_enabled() is enabled
        assert OnyxRuntime.get_cc_pair_access_filter_enforce() is enforce


@pytest.mark.usefixtures("kv_progress_restored", "flags_restored")
def test_enforce_needs_a_complete_backfill(db_session: Session) -> None:
    _store(pending=[1])

    with pytest.raises(OnyxError) as exc_info:
        _set_mode(db_session, CCPairAccessMode.ENFORCE)
    assert exc_info.value.error_code is OnyxErrorCode.FEATURE_NOT_AVAILABLE
    # Shadow does not depend on the backfill.
    assert _set_mode(db_session, CCPairAccessMode.SHADOW).access_mode == (
        CCPairAccessMode.SHADOW
    )


@pytest.mark.usefixtures("kv_progress_restored", "flags_restored")
def test_mode_is_operator_controlled_in_multi_tenant(db_session: Session) -> None:
    _store(pending=[], snapshot=[1])

    with patch.object(search_settings_api, "MULTI_TENANT", True):
        with pytest.raises(OnyxError) as exc_info:
            _set_mode(db_session, CCPairAccessMode.SHADOW)
        assert exc_info.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        assert not _status(db_session).mode_editable
