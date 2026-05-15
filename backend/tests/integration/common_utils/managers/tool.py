import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestTool
from tests.integration.common_utils.test_models import DATestUser


class ToolManager:
    @staticmethod
    def list_tools(
        user_performing_action: DATestUser,
    ) -> list[DATestTool]:
        response = requests.get(
            url=f"{API_SERVER_URL}/tool",
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        return [
            DATestTool(
                id=tool.get("id"),
                name=tool.get("name"),
                description=tool.get("description"),
                display_name=tool.get("display_name"),
                in_code_tool_id=tool.get("in_code_tool_id"),
                enabled=tool.get("enabled"),
            )
            for tool in response.json()
        ]

    @staticmethod
    def get_by_in_code_id(
        in_code_tool_id: str,
        user_performing_action: DATestUser,
    ) -> DATestTool | None:
        for tool in ToolManager.list_tools(user_performing_action):
            if tool.in_code_tool_id == in_code_tool_id:
                return tool
        return None

    @staticmethod
    def set_enabled(
        tool_ids: list[int],
        enabled: bool,
        user_performing_action: DATestUser,
    ) -> requests.Response:
        response = requests.patch(
            url=f"{API_SERVER_URL}/admin/tool/status",
            headers=user_performing_action.headers,
            json={"tool_ids": tool_ids, "enabled": enabled},
        )
        response.raise_for_status()
        return response
