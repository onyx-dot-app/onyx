import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import _validate_voice_api_base


def test_validate_voice_api_base_blocks_private_for_non_azure() -> None:
    with pytest.raises(OnyxError, match="Invalid target URI"):
        _validate_voice_api_base("openai", "http://127.0.0.1:11434")


def test_validate_voice_api_base_allows_private_for_azure() -> None:
    validated = _validate_voice_api_base("azure", "http://127.0.0.1:5000")
    assert validated == "http://127.0.0.1:5000"


def test_validate_voice_api_base_blocks_metadata_for_azure() -> None:
    with pytest.raises(OnyxError, match="Invalid target URI"):
        _validate_voice_api_base("azure", "http://metadata.google.internal/")


def test_validate_voice_api_base_returns_none_for_none() -> None:
    assert _validate_voice_api_base("openai", None) is None
