import requests

from ee.onyx.server.query_and_chat.models import SearchFullResponse
from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestUser


class DocumentSearchManager:
    @staticmethod
    def search_documents(
        query: str,
        user_performing_action: DATestUser | None = None,
    ) -> list[str]:
        """
        Search for documents using the EE search API.

        Args:
            query: The search query string
            user_performing_action: The user performing the search (for auth)

        Returns:
            A list of document content strings (blurbs) from the search results
        """
        search_request = SendSearchQueryRequest(
            search_query=query,
            filters=None,
            stream=False,
        )
        result = requests.post(
            url=f"{API_SERVER_URL}/search/send-search-message",
            json=search_request.model_dump(),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        result.raise_for_status()
        result_json = result.json()
        search_response = SearchFullResponse(**result_json)

        # Return the blurbs as the document content
        # For small documents (like test docs), the blurb should contain the full content
        document_content_list: list[str] = [
            doc.blurb for doc in search_response.search_docs
        ]
        return document_content_list
