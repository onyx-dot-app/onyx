from unittest.mock import MagicMock, patch

from onyx.server.runtime import onyx_runtime
from onyx.server.runtime.onyx_runtime import OnyxRuntime


def test_cc_pair_access_flags_read_the_cache_backend() -> None:
    cache = MagicMock()
    cache.get.side_effect = lambda key: (
        b"true" if key.endswith("cc_pair_access_filter:enabled") else None
    )
    with patch.object(onyx_runtime, "get_cache_backend", return_value=cache):
        assert OnyxRuntime.get_cc_pair_access_filter_enabled()
        assert not OnyxRuntime.get_cc_pair_access_filter_enforce()


def test_cc_pair_access_flags_fall_back_when_the_cache_fails() -> None:
    with (
        patch.object(
            onyx_runtime, "get_cache_backend", side_effect=ConnectionError("down")
        ),
        patch.object(onyx_runtime, "ENABLE_CC_PAIR_ACCESS_FILTER", False),
    ):
        assert not OnyxRuntime.get_cc_pair_access_filter_enabled()
        assert not OnyxRuntime.get_cc_pair_access_filter_enforce()
