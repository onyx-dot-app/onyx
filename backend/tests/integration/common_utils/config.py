import generated.onyx_openapi_client.onyx_openapi_client as onyx_api  # type: ignore[import-untyped]
from tests.integration.common_utils.constants import API_SERVER_URL

api_config = onyx_api.Configuration(host=API_SERVER_URL)
