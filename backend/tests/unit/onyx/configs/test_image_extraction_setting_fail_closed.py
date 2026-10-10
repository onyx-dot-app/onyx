"""Image extraction must stay off when workspace settings cannot be loaded.

`load_settings` returns `Settings()` defaults on failure unless the caller opts
into `raise_on_error`, and the model defaults this feature to True. Without the
opt-in, environments with no DB/Redis (unit tests, the connector-test container)
silently turn image extraction on and hit the file store.
"""

from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled

_STORE = "onyx.server.settings.store"


def _kv_store(load_result: object | Exception) -> MagicMock:
    kv_store = MagicMock()
    if isinstance(load_result, Exception):
        kv_store.load.side_effect = load_result
    else:
        kv_store.load.return_value = load_result
    return kv_store


def test_disabled_when_settings_cannot_be_loaded() -> None:
    kv_store = _kv_store(RuntimeError("Engine not initialized"))
    with patch(f"{_STORE}.get_kv_store", return_value=kv_store):
        assert get_image_extraction_and_analysis_enabled() is False


@pytest.mark.parametrize("stored", [True, False])
def test_follows_stored_setting(stored: bool) -> None:
    kv_store = _kv_store({"image_extraction_and_analysis_enabled": stored})
    cache = MagicMock()
    cache.get.return_value = None
    with (
        patch(f"{_STORE}.get_kv_store", return_value=kv_store),
        patch(f"{_STORE}.get_cache_backend", return_value=cache),
    ):
        assert get_image_extraction_and_analysis_enabled() is stored
