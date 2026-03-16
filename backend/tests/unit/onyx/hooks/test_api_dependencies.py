"""Unit tests for the hooks feature gate."""

from unittest.mock import patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.api_dependencies import require_hook_enabled


class TestRequireHookEnabled:
    def test_raises_when_multi_tenant(self) -> None:
        with (
            patch("onyx.hooks.api_dependencies.MULTI_TENANT", True),
            patch("onyx.hooks.api_dependencies.HOOK_ENABLED", True),
        ):
            with pytest.raises(OnyxError) as exc_info:
                require_hook_enabled()
        assert exc_info.value.error_code is OnyxErrorCode.SINGLE_TENANT_ONLY
        assert exc_info.value.status_code == 400
        assert "multi-tenant" in exc_info.value.detail

    def test_raises_when_flag_disabled(self) -> None:
        with (
            patch("onyx.hooks.api_dependencies.MULTI_TENANT", False),
            patch("onyx.hooks.api_dependencies.HOOK_ENABLED", False),
        ):
            with pytest.raises(OnyxError) as exc_info:
                require_hook_enabled()
        assert exc_info.value.error_code is OnyxErrorCode.ENV_VAR_GATED
        assert exc_info.value.status_code == 400
        assert "HOOK_ENABLED" in exc_info.value.detail

    def test_passes_when_enabled_single_tenant(self) -> None:
        with (
            patch("onyx.hooks.api_dependencies.MULTI_TENANT", False),
            patch("onyx.hooks.api_dependencies.HOOK_ENABLED", True),
        ):
            require_hook_enabled()  # must not raise
