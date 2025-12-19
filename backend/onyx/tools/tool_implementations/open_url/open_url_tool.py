import json
from typing import Any
from typing import cast

from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import OpenURLToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.web_search.providers import (
    get_default_content_provider,
)
from onyx.tools.tool_implementations.web_search.utils import (
    inference_section_from_internet_page_scrape,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

URLS_FIELD = "urls"


def _convert_sections_to_llm_string_with_citations(
    sections: list[InferenceSection],
    existing_citation_mapping: dict[str, int],
    citation_start: int,
) -> tuple[str, dict[int, str]]:
    """Convert InferenceSections to LLM string, reusing existing citations where available.

    Args:
        sections: List of InferenceSection objects to convert.
        existing_citation_mapping: Mapping of document_id -> citation_num for
            documents that have already been cited.
        citation_start: Starting citation number for new citations.

    Returns:
        Tuple of (JSON string for LLM, citation_mapping dict).
        The citation_mapping maps citation_id -> document_id.
    """
    # Build document_id to citation_id mapping, reusing existing citations
    document_id_to_citation_id: dict[str, int] = {}
    citation_mapping: dict[int, str] = {}
    next_citation_id = citation_start

    # First pass: assign citation_ids, reusing existing ones where available
    for section in sections:
        document_id = section.center_chunk.document_id
        if document_id in document_id_to_citation_id:
            # Already assigned in this batch
            continue

        if document_id in existing_citation_mapping:
            # Reuse existing citation number
            citation_id = existing_citation_mapping[document_id]
            document_id_to_citation_id[document_id] = citation_id
            citation_mapping[citation_id] = document_id
        else:
            # Assign new citation number
            document_id_to_citation_id[document_id] = next_citation_id
            citation_mapping[next_citation_id] = document_id
            next_citation_id += 1

    # Second pass: build results
    results = []
    for section in sections:
        chunk = section.center_chunk
        document_id = chunk.document_id
        citation_id = document_id_to_citation_id[document_id]

        # Format updated_at as ISO string if available
        updated_at_str = None
        if chunk.updated_at:
            updated_at_str = chunk.updated_at.isoformat()

        result: dict[str, Any] = {
            "document": citation_id,
            "title": chunk.semantic_identifier,
        }
        if updated_at_str is not None:
            result["updated_at"] = updated_at_str
        result["source_type"] = chunk.source_type.value
        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata)
        result["content"] = section.combined_content

        results.append(result)

    output = {"results": results}
    return json.dumps(output, indent=2), citation_mapping


class OpenURLTool(Tool[OpenURLToolOverrideKwargs]):
    NAME = "open_url"
    DESCRIPTION = "Open and read the content of one or more URLs."
    DISPLAY_NAME = "Open URL"

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        content_provider: WebContentProvider | None = None,
    ) -> None:
        """Initialize the OpenURLTool.

        Args:
            tool_id: Unique identifier for this tool instance.
            emitter: Emitter for streaming packets to the client.
            content_provider: Optional content provider. If not provided,
                will use the default provider from the database or fall back
                to the built-in Onyx web crawler.
        """
        super().__init__(emitter=emitter)
        self._id = tool_id

        if content_provider is not None:
            self._provider = content_provider
        else:
            provider = get_default_content_provider()
            if provider is None:
                raise RuntimeError(
                    "No web content provider available. "
                    "Please configure a content provider or ensure the "
                    "built-in Onyx web crawler can be initialized."
                )
            self._provider = provider

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """OpenURLTool is always available since it falls back to built-in crawler."""
        # The tool can use either a configured provider or the built-in crawler,
        # so it's always available
        return True

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Open and read the content of one or more URLs. Returns the text content of the pages.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        URLS_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of URLs to open and read. Can be a single URL or multiple URLs.",
                        },
                    },
                    "required": [URLS_FIELD],
                },
            },
        }

    def emit_start(self, turn_index: int, tab_index: int) -> None:
        """Emit start packet to signal tool has started."""
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=OpenUrlStart(),
            )
        )

    def run(
        self,
        turn_index: int,
        tab_index: int,
        override_kwargs: OpenURLToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the open URL tool to fetch content from the specified URLs.

        Args:
            turn_index: The current turn index in the conversation.
            tab_index: The tab index for parallel tool calls.
            override_kwargs: Override arguments including starting citation number
                and existing citation_mapping to reuse citations for already-cited URLs.
            **llm_kwargs: Arguments provided by the LLM, including the 'urls' field.

        Returns:
            ToolResponse containing the fetched content and citation mapping.
        """
        urls = cast(list[str], llm_kwargs[URLS_FIELD])

        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=OpenUrlUrls(urls=urls),
            )
        )

        # Fetch content from URLs using the content provider
        web_contents = self._provider.contents(urls)

        # Filter out failed fetches and convert to InferenceSections
        inference_sections = []
        for content in web_contents:
            if content.scrape_successful and content.full_content:
                inference_sections.append(
                    inference_section_from_internet_page_scrape(content)
                )
            else:
                logger.warning(f"Failed to fetch content from URL: {content.link}")

        if not inference_sections:
            # All fetches failed
            failed_urls = [c.link for c in web_contents]
            return ToolResponse(
                rich_response=None,
                llm_facing_response=(
                    f"Failed to fetch content from the following URLs: {', '.join(failed_urls)}"
                ),
            )

        # Convert to SearchDocs for UI display
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=True
        )

        # Emit documents packet AFTER crawling completes
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                tab_index=tab_index,
                obj=OpenUrlDocuments(documents=search_docs),
            )
        )

        # Format for LLM, reusing existing citations where available
        docs_str, citation_mapping = _convert_sections_to_llm_string_with_citations(
            sections=inference_sections,
            existing_citation_mapping=override_kwargs.citation_mapping,
            citation_start=override_kwargs.starting_citation_num,
        )

        return ToolResponse(
            rich_response=SearchDocsResponse(
                search_docs=search_docs,
                citation_mapping=citation_mapping,
            ),
            llm_facing_response=docs_str,
        )
