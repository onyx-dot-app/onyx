from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

import requests
from requests.models import CaseInsensitiveDict

from ee.onyx.server.query_history.models import ChatSessionMinimal
from ee.onyx.server.query_history.models import ChatSessionSnapshot
from onyx.configs.constants import QAFeedbackType
from onyx.server.documents.models import PaginatedReturn
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


class QueryHistoryManager:
    @staticmethod
    def get_query_history_page(
        page_num: int = 0,
        page_size: int = 10,
        feedback_type: QAFeedbackType | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> PaginatedReturn[ChatSessionMinimal]:
        query_params: dict[str, str | int] = {
            "page_num": page_num,
            "page_size": page_size,
        }
        if feedback_type:
            query_params["feedback_type"] = feedback_type.value
        if start_time:
            query_params["start_time"] = start_time.isoformat()
        if end_time:
            query_params["end_time"] = end_time.isoformat()

        response = requests.get(
            url=f"{API_SERVER_URL}/admin/chat-session-history?{urlencode(query_params, doseq=True)}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        data = response.json()
        return PaginatedReturn(
            items=[ChatSessionMinimal(**item) for item in data["items"]],
            total_items=data["total_items"],
        )

    @staticmethod
    def get_chat_session_admin(
        chat_session_id: UUID | str,
        user_performing_action: DATestUser | None = None,
    ) -> ChatSessionSnapshot:
        response = requests.get(
            url=f"{API_SERVER_URL}/admin/chat-session-history/{chat_session_id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return ChatSessionSnapshot(**response.json())

    @staticmethod
    def get_query_history_as_csv(
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        user_performing_action: DATestUser | None = None,
    ) -> tuple[CaseInsensitiveDict[str], str]:
        query_params: dict[str, str | int] = {}
        if start_time:
            query_params["start"] = start_time.isoformat()
        if end_time:
            query_params["end"] = end_time.isoformat()

        response = requests.get(
            url=f"{API_SERVER_URL}/admin/query-history-csv?{urlencode(query_params, doseq=True)}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return response.headers, response.content.decode()
