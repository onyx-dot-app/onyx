from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest


def _existing_provider(custom_config: dict[str, str] | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=123,
        name="provider-name",
        provider="openai",
        api_base=None,
        custom_config=custom_config,
        api_key=SimpleNamespace(get_value=lambda apply_mask=False: "sk-existing"),
        is_auto_mode=False,
        model_configurations=[],
    )


def test_put_llm_provider_keeps_non_null_custom_config_when_change_flag_false() -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    existing = _existing_provider({"think": "true"})
    request = LLMProviderUpsertRequest(
        id=existing.id,
        name=existing.name,
        provider=existing.provider,
        api_key="sk-existing",
        custom_config={"think": "false"},
        custom_config_changed=False,
        api_key_changed=False,
        model_configurations=[],
        groups=[],
        personas=[],
        is_public=True,
    )

    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=existing,
        ),
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider",
            return_value=existing,
        ),
        patch("onyx.server.manage.llm.api._validate_llm_provider_change"),
        patch("onyx.server.manage.llm.api._mask_provider_credentials"),
        patch("onyx.server.manage.llm.api.upsert_llm_provider") as mock_upsert,
    ):
        mock_upsert.side_effect = (
            lambda llm_provider_upsert_request, db_session: llm_provider_upsert_request
        )
        updated = put_llm_provider(request, is_creation=False, _=MagicMock(), db_session=MagicMock())

        assert updated.custom_config == {"think": "false"}


def test_put_llm_provider_falls_back_to_existing_custom_config_when_null() -> None:
    from onyx.server.manage.llm.api import put_llm_provider

    existing = _existing_provider({"think": "true"})
    request = LLMProviderUpsertRequest(
        id=existing.id,
        name=existing.name,
        provider=existing.provider,
        api_key="sk-existing",
        custom_config=None,
        custom_config_changed=False,
        api_key_changed=False,
        model_configurations=[],
        groups=[],
        personas=[],
        is_public=True,
    )

    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=existing,
        ),
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider",
            return_value=existing,
        ),
        patch("onyx.server.manage.llm.api._validate_llm_provider_change"),
        patch("onyx.server.manage.llm.api._mask_provider_credentials"),
        patch("onyx.server.manage.llm.api.upsert_llm_provider") as mock_upsert,
    ):
        mock_upsert.side_effect = (
            lambda llm_provider_upsert_request, db_session: llm_provider_upsert_request
        )
        updated = put_llm_provider(request, is_creation=False, _=MagicMock(), db_session=MagicMock())

        assert updated.custom_config == {"think": "true"}


def test_test_llm_configuration_keeps_non_null_custom_config_when_change_flag_false() -> None:
    from onyx.server.manage.llm.api import test_llm_configuration

    existing = _existing_provider({"think": "true"})
    request = LLMTestRequest(
        id=existing.id,
        provider=existing.provider,
        model="gpt-4o-mini",
        api_key="sk-existing",
        custom_config={"think": "false"},
        api_key_changed=False,
        custom_config_changed=False,
    )

    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=existing,
        ),
        patch("onyx.server.manage.llm.api._validate_llm_provider_change"),
        patch("onyx.server.manage.llm.api.get_llm") as mock_get_llm,
        patch("onyx.server.manage.llm.api.test_llm", return_value=None),
    ):
        test_llm_configuration(request, _=MagicMock(), db_session=MagicMock())
        assert mock_get_llm.call_args.kwargs["custom_config"] == {"think": "false"}


def test_test_llm_configuration_falls_back_to_existing_custom_config_when_null() -> None:
    from onyx.server.manage.llm.api import test_llm_configuration

    existing = _existing_provider({"think": "true"})
    request = LLMTestRequest(
        id=existing.id,
        provider=existing.provider,
        model="gpt-4o-mini",
        api_key="sk-existing",
        custom_config=None,
        api_key_changed=False,
        custom_config_changed=False,
    )

    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=existing,
        ),
        patch("onyx.server.manage.llm.api._validate_llm_provider_change"),
        patch("onyx.server.manage.llm.api.get_llm") as mock_get_llm,
        patch("onyx.server.manage.llm.api.test_llm", return_value=None),
    ):
        test_llm_configuration(request, _=MagicMock(), db_session=MagicMock())
        assert mock_get_llm.call_args.kwargs["custom_config"] == {"think": "true"}