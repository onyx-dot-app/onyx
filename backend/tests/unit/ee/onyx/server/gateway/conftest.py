from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.gateway import api as gateway_api
from onyx.server.settings.models import Settings


@pytest.fixture(autouse=True)
def _gateway_enabled() -> Iterator[None]:
    """_authorize_gateway_request reads the workspace toggle from the KV
    store; keep it enabled (the default) without touching real
    infrastructure. Tests that exercise the disabled path patch it again."""
    with patch.object(gateway_api, "load_settings", MagicMock(return_value=Settings())):
        yield
