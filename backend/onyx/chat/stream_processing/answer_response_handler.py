import abc
from collections.abc import Generator

from langchain_core.messages import BaseMessage

from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import ResponsePart
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import DocumentIdOrderMapping
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


# TODO: remove update() once it is no longer needed
class AnswerResponseHandler(abc.ABC):
    @abc.abstractmethod
    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        raise NotImplementedError


class PassThroughAnswerResponseHandler(AnswerResponseHandler):
    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        content = _message_to_str(response_item)
        yield OnyxAnswerPiece(answer_piece=content)


class DummyAnswerResponseHandler(AnswerResponseHandler):
    def handle_response_part(
        self,
        response_item: BaseMessage | str | None,
        previous_response_items: list[BaseMessage | str],
    ) -> Generator[ResponsePart, None, None]:
        # This is a dummy handler that returns nothing
        yield from []


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

        content = _message_to_str(response_item)

        # Process the new content through the citation processor
        yield from self.citation_processor.process_token(content)


def _message_to_str(message: BaseMessage | str | None) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return message
    content = message.content if isinstance(message, BaseMessage) else message
    if not isinstance(content, str):
        logger.warning(f"Received non-string content: {type(content)}")
        content = str(content) if content is not None else ""
    return content
