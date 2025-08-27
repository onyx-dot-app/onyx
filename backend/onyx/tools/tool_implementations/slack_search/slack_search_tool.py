"""
Slack Search Tool for Slack Bot

This tool allows the Slack bot to search through Slack messages using both
bot and user tokens for enhanced access to public and private channels.
"""

import json
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.context.search.federated.slack_search import slack_bot_retrieval
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchQuery
from onyx.tools.message import ToolResponse
from onyx.tools.models import SearchQueryInfo
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

SLACK_SEARCH_QUERY_FIELD = "query"
SLACK_SEARCH_RESPONSE_SUMMARY_ID = "slack_search_response_summary"
SLACK_SEARCH_FINAL_CONTEXT_DOCUMENTS_ID = "slack_search_final_context_documents"

SLACK_SEARCH_TOOL_DESCRIPTION = """
Searches through Slack messages to find relevant conversations and information.
cUse this tool when the user asks about previous discussions, messages, or information shared in Slack channels.
"""


class SlackSearchResponseSummary(SearchQueryInfo):
    """Summary of Slack search results"""

    query: str
    top_sections: list[InferenceSection]


class SlackSearchToolConfig:
    """Configuration for Slack search tool"""

    def __init__(
        self,
        retrieval_options=None,
        document_pruning_config: DocumentPruningConfig | None = None,
        answer_style_config: AnswerStyleConfig | None = None,
        chunks_above: int | None = None,
        chunks_below: int | None = None,
    ):
        self.retrieval_options = retrieval_options
        self.document_pruning_config = document_pruning_config
        self.answer_style_config = answer_style_config
        self.chunks_above = chunks_above
        self.chunks_below = chunks_below


class SlackSearchTool(Tool[None]):
    _NAME = "slack_search"
    _DISPLAY_NAME = "Slack Search"
    _DESCRIPTION = SLACK_SEARCH_TOOL_DESCRIPTION

    def __init__(
        self,
        db_session: Session,
        bot_token: str,
        user_token: str | None = None,
    ) -> None:
        self.db_session = db_session
        self.bot_token = bot_token
        self.user_token = user_token

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in Slack messages",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        """Build the tool message content from search results"""
        final_context_docs_response = next(
            response
            for response in args
            if response.id == SLACK_SEARCH_FINAL_CONTEXT_DOCUMENTS_ID
        )
        final_context_docs = final_context_docs_response.response

        return json.dumps(
            {
                "slack_search_results": [
                    {
                        "id": doc.id,
                        "title": doc.title,
                        "content": doc.content,
                        "link": doc.link,
                        "metadata": doc.metadata,
                    }
                    for doc in final_context_docs
                ]
            }
        )

    def run(
        self, override_kwargs: None = None, **kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        query_text = kwargs.get("query", "")
        if not query_text:
            logger.warning("No query provided to Slack search tool")
            return

        # Create a search query
        search_query = SearchQuery(
            query=query_text,
            original_query=query_text,
            filters=None,
        )

        # Use the federated search functionality with both tokens
        try:
            chunks = slack_bot_retrieval(
                query=search_query,
                bot_token=self.bot_token,
                user_token=self.user_token,
                db_session=self.db_session,
                limit=10,  # Limit results for Slack bot usage
            )

            # Convert chunks to a simple response format
            search_results = []
            for chunk in chunks:
                search_results.append(
                    {
                        "content": chunk.content,
                        "source": (
                            chunk.source_document.id
                            if chunk.source_document
                            else "unknown"
                        ),
                        "metadata": chunk.metadata,
                    }
                )

            yield ToolResponse(
                id="slack_search_results",
                response={
                    "query": query_text,
                    "results": search_results,
                    "count": len(search_results),
                },
            )

        except Exception as e:
            logger.error(f"Error in Slack search: {e}")
            yield ToolResponse(
                id="slack_search_error",
                response={
                    "error": f"Failed to search Slack: {str(e)}",
                    "query": query_text,
                },
            )
