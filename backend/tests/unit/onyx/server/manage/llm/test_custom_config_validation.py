from unittest.mock import patch

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.api import _validate_custom_config_keys_supported


def test_unmappable_keys_rejected_when_injection_disabled() -> None:
    with patch(
        "onyx.server.manage.llm.api.LLM_CUSTOM_CONFIG_ENV_INJECTION_ENABLED",
        False,
    ):
        with pytest.raises(OnyxError) as exc_info:
            _validate_custom_config_keys_supported(
                provider="cloudflare",
                custom_config={"CLOUDFLARE_ACCOUNT_ID": "acct"},
            )
    assert "CLOUDFLARE_ACCOUNT_ID" in str(exc_info.value)


def test_mappable_keys_accepted_when_injection_disabled() -> None:
    with patch(
        "onyx.server.manage.llm.api.LLM_CUSTOM_CONFIG_ENV_INJECTION_ENABLED",
        False,
    ):
        _validate_custom_config_keys_supported(
            provider=LlmProviderNames.BEDROCK,
            custom_config={
                "AWS_ACCESS_KEY_ID": "akid",
                "AWS_SECRET_ACCESS_KEY": "secret",
                "AWS_REGION_NAME": "us-east-1",
            },
        )
        _validate_custom_config_keys_supported(
            provider="groq",
            custom_config={"GROQ_API_KEY": "gk"},
        )


def test_arbitrary_keys_accepted_when_injection_enabled() -> None:
    with patch(
        "onyx.server.manage.llm.api.LLM_CUSTOM_CONFIG_ENV_INJECTION_ENABLED",
        True,
    ):
        _validate_custom_config_keys_supported(
            provider="cloudflare",
            custom_config={"CLOUDFLARE_ACCOUNT_ID": "acct"},
        )
