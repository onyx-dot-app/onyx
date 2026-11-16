"""User Library (CRAFT_FILE) pairs store files directly and have no connector
class. The indexing checker must not schedule them, and a legacy embedding
swap must not wait for them to index."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.configs.constants import DocumentSource
from onyx.db.enums import ConnectorCredentialPairStatus, SwitchoverType
from onyx.db.models import IndexModelStatus
from onyx.db.swap_index import check_and_perform_index_swap

_UTILS = "onyx.background.celery.tasks.docprocessing.utils"
_SWAP = "onyx.db.swap_index"


def _cc_pair(source: DocumentSource, connector_id: int = 5) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.id = connector_id
    cc_pair.connector.id = connector_id
    cc_pair.connector.source = source
    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    cc_pair.indexing_trigger = None
    cc_pair.prune_after_reindex_requested_at = None
    cc_pair.full_reindex_requested_at = None
    return cc_pair


def _search_settings(status: IndexModelStatus) -> MagicMock:
    search_settings = MagicMock()
    search_settings.id = 1
    search_settings.status = status
    search_settings.use_port_flow = False
    return search_settings


@pytest.mark.parametrize("status", [IndexModelStatus.PRESENT, IndexModelStatus.FUTURE])
@patch(f"{_UTILS}.DISABLE_INDEX_UPDATE_ON_SWAP", False)
@patch(f"{_UTILS}._failed_streak", return_value=[])
@patch(f"{_UTILS}.get_last_attempt_for_cc_pair", return_value=None)
def test_user_library_pair_is_never_scheduled(
    _last_attempt: MagicMock,
    _failed_streak: MagicMock,
    status: IndexModelStatus,
) -> None:
    search_settings = _search_settings(status)

    assert not should_index(
        cc_pair=_cc_pair(DocumentSource.CRAFT_FILE),
        search_settings_instance=search_settings,
        secondary_index_building=False,
        db_session=MagicMock(),
    )
    assert should_index(
        cc_pair=_cc_pair(DocumentSource.MOCK_CONNECTOR),
        search_settings_instance=search_settings,
        secondary_index_building=False,
        db_session=MagicMock(),
    )


@pytest.mark.parametrize(
    ("switchover_type", "count_fn"),
    [
        (
            SwitchoverType.REINDEX,
            "count_unique_cc_pairs_with_successful_index_attempts",
        ),
        (
            SwitchoverType.ACTIVE_ONLY,
            "count_unique_active_cc_pairs_with_successful_index_attempts",
        ),
    ],
)
def test_legacy_swap_does_not_wait_for_user_library_pairs(
    switchover_type: SwitchoverType, count_fn: str
) -> None:
    ingestion_pair = _cc_pair(DocumentSource.INGESTION_API, connector_id=0)
    normal_pair = _cc_pair(DocumentSource.MOCK_CONNECTOR, connector_id=1)
    user_library_pair = _cc_pair(DocumentSource.CRAFT_FILE, connector_id=2)

    future = MagicMock()
    future.id = 9
    future.use_port_flow = False
    future.switchover_type = switchover_type

    swapped = MagicMock()
    with (
        patch(f"{_SWAP}.DISABLE_VECTOR_DB", False),
        patch(
            f"{_SWAP}.get_connector_credential_pairs",
            return_value=[ingestion_pair, normal_pair, user_library_pair],
        ) as get_pairs,
        patch(f"{_SWAP}.get_secondary_search_settings", return_value=future),
        # Only the normal pair finished; the User Library pair never indexes.
        patch(f"{_SWAP}.{count_fn}", return_value=1),
        patch(f"{_SWAP}._perform_index_swap", return_value=swapped) as perform,
    ):
        assert check_and_perform_index_swap(MagicMock()) is swapped

    perform.assert_called_once()
    # The source filter reads cc_pair.connector; load it in the same query.
    assert get_pairs.call_args.kwargs["eager_load_connector"] is True
