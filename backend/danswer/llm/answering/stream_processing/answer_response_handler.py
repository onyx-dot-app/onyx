import abc
from collections.abc import Generator

from langchain_core.messages import BaseMessage

from danswer.chat.models import CitationInfo
from danswer.chat.models import LlmDoc
from danswer.llm.answering.llm_response_handler import ResponsePart
from danswer.llm.answering.stream_processing.citation_processing import (
    CitationProcessor,
)
from danswer.llm.answering.stream_processing.quotes_processing import (
    QuotesProcessor,
)
from danswer.llm.answering.stream_processing.utils import DocumentIdOrderMapping


class AnswerResponseHandler(abc.ABC):
    @abc.abstractmethod
    def handle_response_part(
        self,
        response_item: BaseMessage | None,
        previous_response_items: list[BaseMessage],
    ) -> Generator[ResponsePart, None, None]:
        raise NotImplementedError


class DummyAnswerResponseHandler(AnswerResponseHandler):
    def handle_response_part(
        self,
        response_item: BaseMessage | None,
        previous_response_items: list[BaseMessage],
    ) -> Generator[ResponsePart, None, None]:
        # This is a dummy handler that returns nothing
        yield from []


class CitationResponseHandler(AnswerResponseHandler):
    def __init__(
        self, context_docs: list[LlmDoc], doc_id_to_rank_map: DocumentIdOrderMapping
    ):
        self.context_docs = context_docs
        self.doc_id_to_rank_map = doc_id_to_rank_map
        self.citation_processor = CitationProcessor(
            context_docs=self.context_docs,
            doc_id_to_rank_map=self.doc_id_to_rank_map,
        )
        self.processed_text = ""
        self.citations: list[CitationInfo] = []

    def handle_response_part(
        self,
        response_item: BaseMessage | None,
        previous_response_items: list[BaseMessage],
    ) -> Generator[ResponsePart, None, None]:
        if response_item is None:
            return

        content = (
            response_item.content if isinstance(response_item.content, str) else ""
        )

        # Process the new content through the citation processor
        yield from self.citation_processor.process_token(content)


class QuotesResponseHandler(AnswerResponseHandler):
    def __init__(
        self,
        context_docs: list[LlmDoc],
        is_json_prompt: bool = True,
    ):
        self.quotes_processor = QuotesProcessor(
            context_docs=context_docs,
            is_json_prompt=is_json_prompt,
        )

    def handle_response_part(
        self,
        response_item: BaseMessage | None,
        previous_response_items: list[BaseMessage],
    ) -> Generator[ResponsePart, None, None]:
        if response_item is None:
            yield from self.quotes_processor.process_token(None)
            return

        content = (
            response_item.content if isinstance(response_item.content, str) else ""
        )

        yield from self.quotes_processor.process_token(content)
