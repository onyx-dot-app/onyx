"""Guard that blocks a new reindex while an INSTANT swap is still backfilling the
live index (superseding it would abandon that backfill)."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.enums import EmbeddingPrecision
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import set_new_search_settings

_MODULE = "onyx.server.manage.search_settings"


class _GuardPassed(Exception):
    """Patched into create_search_settings to prove the guard let the request through."""


def _request() -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="test-embedding-model",
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


def _present(use_port_flow: bool, backfill_source_id: int | None) -> MagicMock:
    ss = MagicMock()
    ss.id = 2
    ss.use_port_flow = use_port_flow
    ss.port_backfill_source_id = backfill_source_id
    ss.model_name = "current-model"
    ss.index_name = "danswer_chunk_current"
    return ss


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=True)
@patch(f"{_MODULE}.get_current_search_settings")
def test_blocks_new_reindex_while_instant_backfill_pending(
    mock_current: MagicMock,
    mock_pending: MagicMock,
) -> None:
    mock_current.return_value = _present(use_port_flow=True, backfill_source_id=1)

    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(_request(), _=MagicMock(), db_session=MagicMock())

    assert exc.value.error_code == OnyxErrorCode.CONFLICT
    mock_pending.assert_called_once()


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
@patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=False)
@patch(f"{_MODULE}.get_current_search_settings")
def test_allows_reindex_once_instant_backfill_complete(
    mock_current: MagicMock,
    mock_pending: MagicMock,
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_create: MagicMock,
) -> None:
    # Same INSTANT-promoted PRESENT, but its backfill has drained -> not blocked.
    mock_current.return_value = _present(use_port_flow=True, backfill_source_id=1)

    with pytest.raises(_GuardPassed):
        set_new_search_settings(_request(), _=MagicMock(), db_session=MagicMock())

    mock_pending.assert_called_once()
    mock_create.assert_called_once()


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
@patch(f"{_MODULE}.port_backfill_has_pending_work")
@patch(f"{_MODULE}.get_current_search_settings")
def test_allows_normal_reindex_without_backfill_source(
    mock_current: MagicMock,
    mock_pending: MagicMock,
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_create: MagicMock,
) -> None:
    # A normally-promoted PRESENT has no port_backfill_source_id; the guard must
    # short-circuit before even querying pending work.
    mock_current.return_value = _present(use_port_flow=True, backfill_source_id=None)

    with pytest.raises(_GuardPassed):
        set_new_search_settings(_request(), _=MagicMock(), db_session=MagicMock())

    mock_pending.assert_not_called()
    mock_create.assert_called_once()
