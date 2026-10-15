from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from onyx.db.models import SearchSettings
from onyx.error_handling.exceptions import OnyxError
from onyx.natural_language_processing.embedding_auth import (
    ApiKeyEmbeddingAuth,
    VertexEmbeddingAuth,
)
from onyx.natural_language_processing.search_nlp_models import AuthenticationError
from onyx.natural_language_processing.vertex_auth import VertexEmbeddingConfig
from onyx.server.manage.embedding.api import (
    list_embedding_models,
    list_embedding_providers,
    put_cloud_embedding_provider,
)
from onyx.server.manage.embedding.api import (
    test_embedding_configuration as run_embedding_test,
)
from onyx.server.manage.embedding.models import (
    CloudEmbeddingProviderCreationRequest,
)
from onyx.server.manage.embedding.models import (
    TestEmbeddingRequest as EmbeddingTestRequest,
)
from onyx.utils.encryption import (
    decrypt_bytes_to_string,
    encrypt_string_to_bytes,
    mask_string,
)
from onyx.utils.sensitive import SensitiveValue
from shared_configs.enums import EmbeddingProvider


def _build_sensitive_value(raw_value: str) -> SensitiveValue[str]:
    return SensitiveValue[str](
        encrypted_bytes=encrypt_string_to_bytes(raw_value),
        decrypt_fn=decrypt_bytes_to_string,
    )


def _build_search_settings(raw_api_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        model_name="gemini-embedding-001",
        normalize=False,
        query_prefix="",
        passage_prefix="",
        provider_type=EmbeddingProvider.GOOGLE,
        cloud_provider=SimpleNamespace(
            api_key=_build_sensitive_value(raw_api_key),
            api_url="",
            api_version=None,
            deployment_name=None,
            vertex_config=None,
        ),
        api_url="",
    )


def test_list_embedding_models_masks_api_key() -> None:
    raw_api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    search_settings = _build_search_settings(raw_api_key)

    with patch(
        "onyx.server.manage.embedding.api.get_all_search_settings",
        return_value=[search_settings],
    ):
        response = list_embedding_models(_=MagicMock(), db_session=MagicMock())

    assert len(response) == 1
    assert response[0].api_key == mask_string(raw_api_key)
    assert response[0].api_key != raw_api_key


def test_list_embedding_models_returns_none_for_local_model_api_key() -> None:
    local_search_settings = SimpleNamespace(
        id=1,
        model_name="thenlper/gte-small",
        normalize=False,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        cloud_provider=None,
        api_url=None,
    )

    with patch(
        "onyx.server.manage.embedding.api.get_all_search_settings",
        return_value=[local_search_settings],
    ):
        response = list_embedding_models(_=MagicMock(), db_session=MagicMock())

    assert len(response) == 1
    assert response[0].api_key is None


def test_list_embedding_providers_uses_sensitive_value_masking_once() -> None:
    raw_api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
    provider_model = SimpleNamespace(
        provider_type=EmbeddingProvider.GOOGLE,
        api_key=_build_sensitive_value(raw_api_key),
        api_url="",
        api_version=None,
        deployment_name=None,
        vertex_config=None,
    )

    with patch(
        "onyx.server.manage.embedding.api.fetch_existing_embedding_providers",
        return_value=[provider_model],
    ):
        response = list_embedding_providers(_=MagicMock(), db_session=MagicMock())

    assert len(response) == 1
    assert response[0].api_key == mask_string(raw_api_key)
    assert response[0].api_key != mask_string(mask_string(raw_api_key))


def test_search_settings_api_key_property_returns_raw_value_for_runtime_use() -> None:
    raw_api_key = "sk-runtime-should-use-unmasked-value-1234567890"
    fake_search_settings = SimpleNamespace(
        cloud_provider=SimpleNamespace(api_key=_build_sensitive_value(raw_api_key))
    )

    api_key_property = SearchSettings.__dict__["api_key"]
    assert api_key_property.fget(fake_search_settings) == raw_api_key


def test_switch_to_workload_identity_clears_stored_json_key() -> None:
    request = CloudEmbeddingProviderCreationRequest(
        provider_type=EmbeddingProvider.GOOGLE,
        api_key="old key must be discarded",
        api_key_changed=False,
        vertex_config=VertexEmbeddingConfig(
            auth_method="workload_identity", project_id="my-project"
        ),
    )
    with patch(
        "onyx.server.manage.embedding.api.upsert_cloud_embedding_provider"
    ) as save:
        put_cloud_embedding_provider(request, _=MagicMock(), db_session=MagicMock())
    saved = save.call_args.args[1]
    assert saved.api_key is None
    assert saved.api_key_changed is True
    assert saved.vertex_config == request.vertex_config


def test_connection_test_reuses_saved_api_key() -> None:

    stored = SimpleNamespace(api_key=_build_sensitive_value("stored-secret"))
    request = EmbeddingTestRequest(
        provider_type=EmbeddingProvider.OPENAI, model_name="text-embedding-3-small"
    )
    with (
        patch(
            "onyx.server.manage.embedding.api.fetch_embedding_provider",
            return_value=stored,
        ),
        patch("onyx.server.manage.embedding.probe.EmbeddingModel") as model,
    ):
        run_embedding_test(request, _=MagicMock(), db_session=MagicMock())
    auth = model.call_args.kwargs["auth"]
    assert isinstance(auth, ApiKeyEmbeddingAuth)
    assert auth.resolve_credentials().api_key.get_secret_value() == "stored-secret"


def test_workload_identity_connection_test_never_loads_saved_key() -> None:

    request = EmbeddingTestRequest(
        provider_type=EmbeddingProvider.GOOGLE,
        model_name="gemini-embedding-2",
        vertex_config=VertexEmbeddingConfig(
            auth_method="workload_identity", project_id="target"
        ),
    )
    with (
        patch("onyx.server.manage.embedding.api.fetch_embedding_provider") as fetch,
        patch("onyx.server.manage.embedding.probe.EmbeddingModel") as model,
    ):
        run_embedding_test(request, _=MagicMock(), db_session=MagicMock())
    fetch.assert_not_called()
    assert isinstance(model.call_args.kwargs["auth"], VertexEmbeddingAuth)
    assert not model.call_args.kwargs["auth"].uses_api_key


def test_gateway_connection_test_reuses_saved_api_key() -> None:
    # Editing a Bifrost connection sends no key; the stored virtual key must be used.
    stored = SimpleNamespace(api_key=_build_sensitive_value("sk-bf-stored"))
    request = EmbeddingTestRequest(
        provider_type=EmbeddingProvider.BIFROST,
        api_url="https://bifrost.example",
        model_name="openai/text-embedding-3-small",
    )
    with (
        patch(
            "onyx.server.manage.embedding.api.fetch_embedding_provider",
            return_value=stored,
        ) as fetch,
        patch("onyx.server.manage.embedding.probe.EmbeddingModel") as model,
    ):
        run_embedding_test(request, _=MagicMock(), db_session=MagicMock())
    fetch.assert_called_once()
    auth = model.call_args.kwargs["auth"]
    assert isinstance(auth, ApiKeyEmbeddingAuth)
    api_key = auth.resolve_credentials().api_key
    assert api_key is not None
    assert api_key.get_secret_value() == "sk-bf-stored"


def test_saving_a_gateway_without_a_new_key_keeps_the_stored_key() -> None:
    request = CloudEmbeddingProviderCreationRequest(
        provider_type=EmbeddingProvider.BIFROST,
        api_url="https://bifrost.example",
        api_key=None,
        api_key_changed=False,
    )
    with patch(
        "onyx.server.manage.embedding.api.upsert_cloud_embedding_provider"
    ) as save:
        put_cloud_embedding_provider(request, _=MagicMock(), db_session=MagicMock())
    saved = save.call_args.args[1]
    assert saved.api_key_changed is False


def test_a_rejected_key_names_the_key_as_the_problem() -> None:
    request = EmbeddingTestRequest(
        provider_type=EmbeddingProvider.BIFROST,
        api_key="sk-bf-wrong",
        api_url="https://bifrost.example",
        model_name="openai/text-embedding-3-small",
    )
    with patch("onyx.server.manage.embedding.probe.EmbeddingModel") as model:
        model.return_value.encode.side_effect = AuthenticationError(provider="bifrost")
        with pytest.raises(OnyxError) as exc:
            run_embedding_test(request, _=MagicMock(), db_session=MagicMock())
    assert "rejected the API key" in exc.value.detail
