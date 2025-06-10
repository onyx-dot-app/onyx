import httpx
import pytest

from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_HOST
from tests.integration.common_utils.constants import MOCK_CONNECTOR_SERVER_PORT


@pytest.fixture
def mock_server_client() -> httpx.Client:
    print(
        f"Initializing mock server client with host: "
        f"{MOCK_CONNECTOR_SERVER_HOST} and port: "
        f"{MOCK_CONNECTOR_SERVER_PORT}"
    )
    return httpx.Client(
        base_url=f"http://{MOCK_CONNECTOR_SERVER_HOST}:{MOCK_CONNECTOR_SERVER_PORT}",
        timeout=5.0,
    )
