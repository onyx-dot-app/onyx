"""Guard that proves a Bifrost model embeds at the set dimension before a reindex."""

from collections.abc import Iterator
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
    model_dim: int,
    reduced_dimension: int | None = None,
    provider_type: EmbeddingProvider = EmbeddingProvider.BIFROST,
) -> SearchSettingsCreationRequest:
    return SearchSettingsCreationRequest(
        model_name="openai/text-embedding-3-large",
        model_dim=model_dim,
        normalize=False,
        query_prefix=None,
        passage_prefix=None,
        provider_type=provider_type,
        index_name=None,
        multipass_indexing=False,
        reduced_dimension=reduced_dimension,
        enable_contextual_rag=False,
        contextual_rag_model_configuration_id=None,
    )


def _provider(
    provider_type: EmbeddingProvider = EmbeddingProvider.BIFROST,
) -> MagicMock:
    provider = MagicMock()
    provider.provider_type = provider_type
    provider.api_url = "https://bifrost.example"
    provider.api_key.get_value.return_value = "sk-bf-stored"
    return provider


@pytest.fixture
def mock_provider() -> Iterator[MagicMock]:
    with patch(f"{_MODULE}.get_embedding_provider_from_provider_type") as get_provider:
        get_provider.return_value = _provider()
        yield get_provider


@pytest.fixture(autouse=True)
def _other_checks_pass() -> Iterator[None]:
    with (
        patch(f"{_MODULE}.validate_contextual_rag_model"),
        patch(f"{_MODULE}._validate_vector_quantization_supported"),
        patch(f"{_MODULE}.get_current_search_settings", side_effect=_GuardPassed),
    ):
        yield


@patch(f"{_MODULE}.probe_embedding_dimension", return_value=3072)
def test_rejects_a_dimension_the_model_does_not_return(
    mock_probe: MagicMock,
    mock_provider: MagicMock,  # noqa: ARG001
) -> None:
    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(_request(1536), _=MagicMock(), db_session=MagicMock())

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert "3072" in exc.value.detail and "1536" in exc.value.detail
    mock_probe.assert_called_once()


@pytest.mark.parametrize(
    ("model_dim", "reduced_dimension", "returned"),
    [(3072, None, 3072), (3072, 256, 256)],
)
@patch(f"{_MODULE}.probe_embedding_dimension")
def test_probes_the_stored_provider_and_accepts_a_matching_dimension(
    mock_probe: MagicMock,
    mock_provider: MagicMock,  # noqa: ARG001
    model_dim: int,
    reduced_dimension: int | None,
    returned: int,
) -> None:
    mock_probe.return_value = returned

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _request(model_dim, reduced_dimension),
            _=MagicMock(),
            db_session=MagicMock(),
        )

    kwargs = mock_probe.call_args.kwargs
    assert kwargs["provider_type"] == EmbeddingProvider.BIFROST
    assert kwargs["api_url"] == "https://bifrost.example"
    assert kwargs["api_key"] == "sk-bf-stored"
    assert kwargs["model_name"] == "openai/text-embedding-3-large"
    assert kwargs["reduced_dimension"] == reduced_dimension
    assert kwargs["auth"].resolve_credentials().api_key.get_secret_value() == (
        "sk-bf-stored"
    )


@patch(f"{_MODULE}.probe_embedding_dimension")
def test_other_cloud_providers_are_not_probed(
    mock_probe: MagicMock, mock_provider: MagicMock
) -> None:
    mock_provider.return_value = _provider(EmbeddingProvider.OPENAI)

    with pytest.raises(_GuardPassed):
        set_new_search_settings(
            _request(3072, provider_type=EmbeddingProvider.OPENAI),
            _=MagicMock(),
            db_session=MagicMock(),
        )

    mock_probe.assert_not_called()


@patch(f"{_MODULE}.probe_embedding_dimension")
def test_a_missing_provider_is_rejected_before_probing(
    mock_probe: MagicMock, mock_provider: MagicMock
) -> None:
    mock_provider.return_value = None

    with pytest.raises(OnyxError) as exc:
        set_new_search_settings(_request(3072), _=MagicMock(), db_session=MagicMock())

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    mock_probe.assert_not_called()
