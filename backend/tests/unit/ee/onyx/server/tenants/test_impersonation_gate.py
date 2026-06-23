"""Unit tests for the impersonation feature gate."""

from unittest.mock import patch

import pytest

from ee.onyx.server.tenants.admin_api import require_impersonation_enabled
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


class TestRequireImpersonationEnabled:
    def test_raises_when_disabled(self) -> None:
        with patch("ee.onyx.server.tenants.admin_api.IMPERSONATION_ENABLED", False):
            with pytest.raises(OnyxError) as exc_info:
                require_impersonation_enabled()
        assert exc_info.value.error_code is OnyxErrorCode.ENV_VAR_GATED
        assert exc_info.value.status_code == 403

    def test_passes_when_enabled(self) -> None:
        with patch("ee.onyx.server.tenants.admin_api.IMPERSONATION_ENABLED", True):
            require_impersonation_enabled()  # must not raise
