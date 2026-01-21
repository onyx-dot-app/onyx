import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestTool
from tests.integration.common_utils.test_models import DATestUser


class ToolManager:
    @staticmethod
    def list_tools(
        user_performing_action: DATestUser | None = None,
    ) -> list[DATestTool]:
        response = requests.get(
            url=f"{API_SERVER_URL}/tool",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [
            DATestTool(
                id=tool.get("id"),
                name=tool.get("name"),
                description=tool.get("description"),
                display_name=tool.get("display_name"),
                in_code_tool_id=tool.get("in_code_tool_id"),
            )
            for tool in response.json()
        ]
