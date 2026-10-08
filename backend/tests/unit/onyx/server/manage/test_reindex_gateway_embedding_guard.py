"""Guard that proves a Bifrost model embeds at the set dimension before a reindex."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import set_new_search_settings
from shared_configs.enums import EmbeddingProvider

_MODULE = "onyx.server.manage.search_settings"


class _GuardPassed(Exception):
    """Patched into get_current_search_settings to prove the guard let the request through."""


def _request(
    model_dim: int, reduced_dimension: int | None = None
) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="openai/text-embedding-3-large",
        model_dim=model_dim,
        normalize=False,
        query_prefix=None,
        passage_prefix=None,
        provider_type=EmbeddingProvider.BIFROST,
        index_name=None,
        multipass_indexing=False,
        reduced_dimension=reduced_dimension,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.provider_type = EmbeddingProvider.BIFROST
    provider.api_url = "https://bifrost.example"
    provider.api_key = None
    return provider


@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}._validate_vector_quantization_supported", MagicMock())
@patch(f"{_MODULE}.get_current_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_embedding_provider_from_provider_type", return_value=_provider())
@patch(f"{_MODULE}.run_embedding_test", return_value=3072)
def test_rejects_a_dimension_the_model_does_not_return(
    mock_test: MagicMock,
    _mock_provider: MagicMock,
    _mock_current: MagicMock,
) -> None:
    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(_request(1536), _=MagicMock(), db_session=MagicMock())

    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert "3072" in exc.value.detail
    mock_test.assert_called_once()


@pytest.mark.parametrize(
    ("model_dim", "reduced_dimension", "returned"),
    [(3072, None, 3072), (3072, 256, 256)],
)
@patch(f"{_MODULE}.validate_contextual_rag_model", MagicMock())
@patch(f"{_MODULE}._validate_vector_quantization_supported", MagicMock())
@patch(f"{_MODULE}.get_current_search_settings", side_effect=_GuardPassed)
@patch(f"{_MODULE}.get_embedding_provider_from_provider_type", return_value=_provider())
@patch(f"{_MODULE}.run_embedding_test")
def test_accepts_a_matching_dimension(
    mock_test: MagicMock,
    _mock_provider: MagicMock,
    _mock_current: MagicMock,
    model_dim: int,
    reduced_dimension: int | None,
    returned: int,
) -> None:
    mock_test.return_value = returned

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _request(model_dim, reduced_dimension),
            _=MagicMock(),
            db_session=MagicMock(),
        )

    assert mock_test.call_args.kwargs["reduced_dimension"] == reduced_dimension
