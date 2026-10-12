from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.gateway import api as gateway_api
from onyx.server.settings.models import Settings, Tier


@pytest.fixture(autouse=True)
def _gateway_enabled() -> Iterator[None]:
    """_authorize_gateway_request reads the workspace toggle and tier; keep
    the gateway enabled on a Business tier without touching real
    infrastructure. Tests that exercise other paths patch them again."""
    with (
        patch.object(gateway_api, "load_settings", MagicMock(return_value=Settings())),
        patch.object(gateway_api, "get_tier", MagicMock(return_value=Tier.BUSINESS)),
    ):
        yield
