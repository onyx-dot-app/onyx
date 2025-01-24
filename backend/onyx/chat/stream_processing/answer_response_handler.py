import abc
from collections.abc import Generator
from typing import Any
from typing import cast

from langchain_core.messages import BaseMessage

from onyx.chat.llm_response_handler import ResponsePart
from onyx.chat.models import CitationInfo
from onyx.chat.models import LlmDoc
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import DocumentIdOrderMapping
from onyx.utils.logger import setup_logger

logger = setup_logger()


class AnswerResponseHandler(abc.ABC):
    @abc.abstractmethod
    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        raise NotImplementedError

    @abc.abstractmethod
    def update(self, state_update: Any) -> None:
        raise NotImplementedError


class DummyAnswerResponseHandler(AnswerResponseHandler):
    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        # This is a dummy handler that returns nothing
        yield from []

    def update(self, state_update: Any) -> None:
        pass


class CitationResponseHandler(AnswerResponseHandler):
    def __init__(
        self,
        context_docs: list[LlmDoc],
        final_doc_id_to_rank_map: DocumentIdOrderMapping,
        display_doc_id_to_rank_map: DocumentIdOrderMapping,
    ):
        self.context_docs = context_docs
        self.final_doc_id_to_rank_map = final_doc_id_to_rank_map
        self.display_doc_id_to_rank_map = display_doc_id_to_rank_map
        self.citation_processor = CitationProcessor(
            context_docs=self.context_docs,
            final_doc_id_to_rank_map=self.final_doc_id_to_rank_map,
            display_doc_id_to_rank_map=self.display_doc_id_to_rank_map,
        )
        self.processed_text = ""
        self.citations: list[CitationInfo] = []

        # TODO remove this after citation issue is resolved
        logger.debug(f"Document to ranking map {self.final_doc_id_to_rank_map}")

    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        if response_item is None:
            return

        content = (
            response_item.content
            if isinstance(response_item, BaseMessage)
            else response_item
        )

        # Ensure content is a string
        if not isinstance(content, str):
            logger.warning(f"Received non-string content: {type(content)}")
            content = str(content) if content is not None else ""

        # Process the new content through the citation processor
        yield from self.citation_processor.process_token(content)

    def update(self, state_update: Any) -> None:
        state = cast(
            tuple[list[LlmDoc], DocumentIdOrderMapping, DocumentIdOrderMapping],
            state_update,
        )
        self.context_docs = state[0]
        self.final_doc_id_to_rank_map = state[1]
        self.display_doc_id_to_rank_map = state[2]
        self.citation_processor = CitationProcessor(
            context_docs=self.context_docs,
            final_doc_id_to_rank_map=self.final_doc_id_to_rank_map,
            display_doc_id_to_rank_map=self.display_doc_id_to_rank_map,
        )


def BaseMessage_to_str(message: BaseMessage) -> str:
    content = message.content if isinstance(message, BaseMessage) else message
    if not isinstance(content, str):
        logger.warning(f"Received non-string content: {type(content)}")
        content = str(content) if content is not None else ""
    return content


# class CitationMultiResponseHandler(AnswerResponseHandler):
#     def __init__(self) -> None:
#         self.channel_processors: dict[str, CitationProcessor] = {}
#         self._default_channel = "__default__"

#     def register_default_channel(
#         self,
#         context_docs: list[LlmDoc],
#         final_doc_id_to_rank_map: DocumentIdOrderMapping,
#         display_doc_id_to_rank_map: DocumentIdOrderMapping,
#     ) -> None:
#         """Register the default channel with its associated documents and ranking maps."""
#         self.register_channel(
#             channel_id=self._default_channel,
#             context_docs=context_docs,
#             final_doc_id_to_rank_map=final_doc_id_to_rank_map,
#             display_doc_id_to_rank_map=display_doc_id_to_rank_map,
#         )

#     def register_channel(
#         self,
#         channel_id: str,
#         context_docs: list[LlmDoc],
#         final_doc_id_to_rank_map: DocumentIdOrderMapping,
#         display_doc_id_to_rank_map: DocumentIdOrderMapping,
#     ) -> None:
#         """Register a new channel with its associated documents and ranking maps."""
#         self.channel_processors[channel_id] = CitationProcessor(
#             context_docs=context_docs,
#             final_doc_id_to_rank_map=final_doc_id_to_rank_map,
#             display_doc_id_to_rank_map=display_doc_id_to_rank_map,
#         )

#     def handle_response_part(
#         self,
#         response_item: BaseMessage | str | None,
#         previous_response_items: list[BaseMessage | str],
#     ) -> Generator[ResponsePart, None, None]:
#         """Default implementation that uses the default channel."""

#         yield from self.handle_channel_response(
#             response_item=content,
#             previous_response_items=previous_response_items,
#             channel_id=self._default_channel,
#         )

#     def handle_channel_response(
#         self,
#         response_item: ResponsePart | str | None,
#         previous_response_items: list[ResponsePart | str],
#         channel_id: str,
#     ) -> Generator[ResponsePart, None, None]:
#         """Process a response part for a specific channel."""
#         if channel_id not in self.channel_processors:
#             raise ValueError(f"Attempted to process response for unregistered channel {channel_id}")

#         if response_item is None:
#             return

#         content = (
#             response_item.content if isinstance(response_item, BaseMessage) else response_item
#         )

#         # Ensure content is a string
#         if not isinstance(content, str):
#             logger.warning(f"Received non-string content: {type(content)}")
#             content = str(content) if content is not None else ""

#         # Process the new content through the channel's citation processor
#         yield from self.channel_processors[channel_id].multi_process_token(content)

#     def remove_channel(self, channel_id: str) -> None:
#         """Remove a channel and its associated processor."""
#         if channel_id in self.channel_processors:
#             del self.channel_processors[channel_id]
