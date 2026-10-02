"""Guard that rejects a vector quantization level the OpenSearch cluster is too
old to index, before the reindex writes anything."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.enums import VectorQuantization
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import set_new_search_settings

_MODULE = "onyx.server.manage.search_settings"


class _GuardPassed(Exception):
    """Patched into create_search_settings to prove the guard let the request through."""


def _request(vector_quantization: VectorQuantization) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="test-embedding-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        index_name=None,
        multipass_indexing=False,
        reduced_dimension=None,
        vector_quantization=vector_quantization,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )


def _present() -> MagicMock:
    search_settings = MagicMock()
    search_settings.id = 2
    search_settings.use_port_flow = True
    search_settings.port_backfill_source_id = None
    search_settings.model_name = "current-model"
    search_settings.index_name = "danswer_chunk_current"
    return search_settings


def _mock_cluster_version(
    mock_client_class: MagicMock, cluster_version: tuple[int, int] | None
) -> None:
    opensearch_client = mock_client_class.return_value.__enter__.return_value
    opensearch_client.get_opensearch_version.return_value = cluster_version


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.create_search_settings")
@patch(f"{_MODULE}.OpenSearchClient")
def test_rejects_one_bit_on_opensearch_older_than_3_6(
    mock_client_class: MagicMock,
    mock_create: MagicMock,
) -> None:
    _mock_cluster_version(mock_client_class, (3, 5))

    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(
            _request(VectorQuantization.SCALAR_1_BIT),
            _=MagicMock(),
            db_session=MagicMock(),
        )

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    mock_create.assert_not_called()


@pytest.mark.parametrize(
    ("vector_quantization", "cluster_version"),
    [
        (VectorQuantization.SCALAR_1_BIT, (3, 6)),
        # The cluster does not report an OpenSearch version.
        (VectorQuantization.SCALAR_1_BIT, None),
        (VectorQuantization.SCALAR_7_BIT, (3, 5)),
    ],
)
@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
@patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=False)
@patch(f"{_MODULE}.get_current_search_settings")
@patch(f"{_MODULE}.OpenSearchClient")
def test_allows_supported_quantization(
    mock_client_class: MagicMock,
    mock_current: MagicMock,
    mock_pending: MagicMock,  # noqa: ARG001
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_create: MagicMock,
    vector_quantization: VectorQuantization,
    cluster_version: tuple[int, int] | None,
) -> None:
    _mock_cluster_version(mock_client_class, cluster_version)
    mock_current.return_value = _present()

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _request(vector_quantization), _=MagicMock(), db_session=MagicMock()
        )

    mock_create.assert_called_once()


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}.create_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
@patch(f"{_MODULE}.port_backfill_has_pending_work", return_value=False)
@patch(f"{_MODULE}.get_current_search_settings")
@patch(f"{_MODULE}.OpenSearchClient")
def test_no_quantization_skips_the_version_check(
    mock_client_class: MagicMock,
    mock_current: MagicMock,
    mock_pending: MagicMock,  # noqa: ARG001
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_create: MagicMock,  # noqa: ARG001
) -> None:
    mock_current.return_value = _present()

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _request(VectorQuantization.NONE), _=MagicMock(), db_session=MagicMock()
        )

    mock_client_class.assert_not_called()
