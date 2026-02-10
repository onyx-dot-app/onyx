from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.db.models import SearchSettings
from onyx.server.manage.embedding.api import list_embedding_models
from onyx.server.manage.embedding.api import list_embedding_providers
from onyx.utils.encryption import decrypt_bytes_to_string
from onyx.utils.encryption import encrypt_string_to_bytes
from onyx.utils.encryption import mask_string
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
