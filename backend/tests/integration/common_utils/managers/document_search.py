import requests

from danswer.search.enums import LLMEvaluationType
from danswer.search.enums import SearchType
from danswer.search.models import RetrievalDetails
from danswer.search.models import SavedSearchDocWithContent
from ee.danswer.server.query_and_chat.models import DocumentSearchRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


class DocumentSearchManager:
    @staticmethod
    def search_documents(
        query: str,
        search_type: SearchType = SearchType.KEYWORD,
        user_performing_action: DATestUser | None = None,
    ) -> list[str]:
        search_request = DocumentSearchRequest(
            message=query,
            search_type=search_type,
            retrieval_options=RetrievalDetails(),
            evaluation_type=LLMEvaluationType.SKIP,
        )
        result = requests.post(
            url=f"{API_SERVER_URL}/query/document-search",
            json=search_request.model_dump(),
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        result.raise_for_status()
        result_json = result.json()
        top_documents: list[SavedSearchDocWithContent] = [
            SavedSearchDocWithContent(**doc) for doc in result_json["top_documents"]
        ]
        document_content_list: list[str] = [doc.content for doc in top_documents]
        return document_content_list
