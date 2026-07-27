"""Guards on set_new_search_settings: one re-index at a time (refuse while a secondary
FUTURE exists), and the name-reuse guard pulls an unreclaimed occupant of the target index
into the reclaim cycle instead of blocking on a manual admin delete."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.enums import EmbeddingPrecision
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import (
    _guard_index_name_reuse,
    set_new_search_settings,
)

_MODULE = "onyx.server.manage.search_settings"


class _GuardPassed(Exception):
    """Patched into create_search_settings to prove the guards let the request through."""


def _request() -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="new-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )


def _present() -> MagicMock:
    # No INSTANT backfill, so that earlier guard short-circuits before these.
    ss = MagicMock()
    ss.use_port_flow = False
    ss.port_backfill_source_id = None
    ss.model_name = "current-model"
    ss.index_name = "danswer_chunk_current"
    return ss


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.get_secondary_search_settings")
@patch(f"{_MODULE}.get_current_search_settings")
def test_refused_while_a_reindex_is_in_progress(
    mock_current: MagicMock,
    mock_secondary: MagicMock,
) -> None:
    # A secondary FUTURE exists -> a new reindex can't supersede it; refuse.
    mock_current.return_value = _present()
    mock_secondary.return_value = MagicMock()

    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(_request(), _=MagicMock(), db_session=MagicMock())
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert "already in progress" in exc.value.detail.lower()


@patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.set_reclaim_intent_on_current__no_commit", MagicMock())
@patch(f"{_MODULE}.compute_wont_port_cc_pair_ids", return_value=[])
@patch(f"{_MODULE}._guard_index_name_reuse", MagicMock())
@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
@patch(f"{_MODULE}.get_current_search_settings")
def test_proceeds_when_no_reindex_in_progress(
    mock_current: MagicMock,
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_wont: MagicMock,  # noqa: ARG001
    mock_create: MagicMock,  # noqa: ARG001
) -> None:
    # No secondary -> the guards pass and the reindex proceeds to create the FUTURE.
    mock_current.return_value = _present()

    with pytest.raises(_GuardPassed):
        set_new_search_settings(_request(), _=MagicMock(), db_session=MagicMock())


@patch(f"{_MODULE}.OLD_INDEX_RECLAIM_ENABLED", True)
@patch(f"{_MODULE}.enqueue_index_reclaim")
@patch(f"{_MODULE}.mark_abandoned_future_for_reclaim__no_commit")
@patch(f"{_MODULE}.find_unreclaimed_past_by_index_name")
def test_name_reuse_guard_pulls_occupant_into_reclaim(
    mock_find: MagicMock,
    mock_mark: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    # The target name is held by an unreclaimed PAST (e.g. legacy NULL) -> mark it for
    # reclaim + kick it (no manual delete), commit, then refuse so the caller retries.
    occupant = MagicMock()
    occupant.id = 5
    mock_find.return_value = [occupant]
    db_session = MagicMock()

    with pytest.raises(OnyxError) as exc:
        _guard_index_name_reuse(db_session, "danswer_chunk_x")
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    mock_mark.assert_called_once_with(occupant)
    db_session.commit.assert_called_once()
    mock_enqueue.assert_called_once()


@patch(f"{_MODULE}.enqueue_index_reclaim")
@patch(f"{_MODULE}.mark_abandoned_future_for_reclaim__no_commit")
@patch(f"{_MODULE}.find_unreclaimed_past_by_index_name", return_value=[])
def test_name_reuse_guard_noop_when_name_free(
    mock_find: MagicMock,  # noqa: ARG001
    mock_mark: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    # No occupant -> the guard is a no-op (nothing marked, nothing kicked, no raise).
    _guard_index_name_reuse(MagicMock(), "danswer_chunk_free")
    mock_mark.assert_not_called()
    mock_enqueue.assert_not_called()


@patch(f"{_MODULE}.OLD_INDEX_RECLAIM_ENABLED", False)
@patch(f"{_MODULE}.enqueue_index_reclaim")
@patch(f"{_MODULE}.mark_abandoned_future_for_reclaim__no_commit")
@patch(f"{_MODULE}.find_unreclaimed_past_by_index_name")
def test_name_reuse_guard_refuses_without_marking_when_reclaim_disabled(
    mock_find: MagicMock,
    mock_mark: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    # Reclaim off -> refuse without marking/kicking (the reclaim task would no-op, so
    # marking DELETING would only strand the row).
    mock_find.return_value = [MagicMock()]

    with pytest.raises(OnyxError) as exc:
        _guard_index_name_reuse(MagicMock(), "danswer_chunk_x")
    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    assert "reclamation is disabled" in exc.value.detail.lower()
    mock_mark.assert_not_called()
    mock_enqueue.assert_not_called()
