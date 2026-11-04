"""The LLM admin api_base guard must reject internal targets at the default
SSRF level, let local model servers reach private hosts, and always block the
cloud-metadata range."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.llm.api import (
    _validate_llm_api_base,
    get_ollama_available_models,
    get_openrouter_available_models,
)
from onyx.server.manage.llm.models import OllamaModelsRequest, OpenRouterModelsRequest
from onyx.server.security.models import SSRFProtectionLevel


def _validate(
    api_base: str | None,
    *,
    allow_local_server: bool = False,
    level: SSRFProtectionLevel = SSRFProtectionLevel.VALIDATE_ALL,
) -> None:
    settings = SimpleNamespace(ssrf_protection_level=level)
    with patch(
        "onyx.server.manage.llm.api.get_security_settings", return_value=settings
    ):
        _validate_llm_api_base(
            api_base, resolve_dns=False, allow_local_server=allow_local_server
        )


def _assert_rejected(api_base: str, *, allow_local_server: bool = False) -> None:
    with pytest.raises(OnyxError) as exc_info:
        _validate(api_base, allow_local_server=allow_local_server)
    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR


def test_metadata_ip_rejected() -> None:
    _assert_rejected("http://169.254.169.254/latest/meta-data/")


def test_loopback_rejected_at_default_level() -> None:
    _assert_rejected("http://127.0.0.1:11434")


def test_private_range_rejected_at_default_level() -> None:
    _assert_rejected("http://10.0.0.5:8000/v1")


def test_loopback_allowed_for_local_server() -> None:
    _validate("http://127.0.0.1:11434", allow_local_server=True)
    _validate("http://localhost:11434", allow_local_server=True)
    _validate("http://192.168.1.20:1234/v1", allow_local_server=True)


def test_localhost_name_rejected_at_default_level() -> None:
    _assert_rejected("http://localhost:4000/v1")


def test_metadata_ip_rejected_even_for_local_server() -> None:
    _assert_rejected(
        "http://169.254.169.254/latest/meta-data/", allow_local_server=True
    )


def test_private_range_allowed_when_setting_permits() -> None:
    _validate("http://10.0.0.5:8000/v1", level=SSRFProtectionLevel.DISABLED)


def test_public_https_url_accepted() -> None:
    _validate("https://openrouter.ai/api/v1")


def test_non_http_scheme_rejected() -> None:
    _assert_rejected("ftp://openrouter.ai/api/v1")


def test_embedded_credentials_rejected() -> None:
    _assert_rejected("https://user:pass@openrouter.ai/api/v1")


def test_empty_api_base_is_skipped() -> None:
    _validate(None)
    _validate("")
    _validate("   ")


def test_ollama_discovery_rejects_metadata_as_validation_error() -> None:
    # The SSRF rejection must surface as the guard's 400, not the 502 catch-all.
    with pytest.raises(OnyxError) as exc_info:
        get_ollama_available_models(
            OllamaModelsRequest(api_base="http://169.254.169.254"),
            MagicMock(),
            MagicMock(),
        )
    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR


def test_openrouter_discovery_rejects_loopback_as_validation_error() -> None:
    with pytest.raises(OnyxError) as exc_info:
        get_openrouter_available_models(
            OpenRouterModelsRequest(api_base="http://127.0.0.1:9/", api_key="x"),
            MagicMock(),
            MagicMock(),
        )
    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR
