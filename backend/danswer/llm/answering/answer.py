from collections.abc import Iterator
from typing import cast

from langchain.schema.messages import BaseMessage

from danswer.chat.models import AnswerQuestionPossibleReturn
from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import QA_PROMPT_OVERRIDE
from danswer.configs.chat_configs import QA_TIMEOUT
from danswer.llm.answering.doc_pruning import prune_documents
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import LLMConfig
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.models import StreamProcessor
from danswer.llm.answering.prompts.citations_prompt import build_citations_prompt
from danswer.llm.answering.prompts.quotes_prompt import (
    build_quotes_prompt,
)
from danswer.llm.answering.stream_processing.citation_processing import (
    build_citation_processor,
)
from danswer.llm.answering.stream_processing.quotes_processing import (
    build_quotes_processor,
)
from danswer.llm.factory import get_default_llm
from danswer.llm.utils import get_default_llm_tokenizer


def _get_stream_processor(
    context_docs: list[LlmDoc],
    search_order_docs: list[LlmDoc],
    answer_style_configs: AnswerStyleConfig,
) -> StreamProcessor:
    if answer_style_configs.citation_config:
        return build_citation_processor(
            context_docs=context_docs, search_order_docs=search_order_docs
        )
    if answer_style_configs.quotes_config:
        return build_quotes_processor(
            context_docs=context_docs, is_json_prompt=not (QA_PROMPT_OVERRIDE == "weak")
        )

    raise RuntimeError("Not implemented yet")


class Answer:
    def __init__(
        self,
        question: str,
        docs: list[LlmDoc],
        answer_style_config: AnswerStyleConfig,
        llm_config: LLMConfig,
        prompt_config: PromptConfig,
        # must be the same length as `docs`. If None, all docs are considered "relevant"
        doc_relevance_list: list[bool] | None = None,
        message_history: list[PreviousMessage] | None = None,
        single_message_history: str | None = None,
        timeout: int = QA_TIMEOUT,
    ) -> None:
        if single_message_history and message_history:
            raise ValueError(
                "Cannot provide both `message_history` and `single_message_history`"
            )

        self.question = question
        self.docs = docs
        self.doc_relevance_list = doc_relevance_list
        self.message_history = message_history or []
        # used for QA flow where we only want to send a single message
        self.single_message_history = single_message_history

        self.answer_style_config = answer_style_config
        self.llm_config = llm_config
        self.prompt_config = prompt_config

        self.llm = get_default_llm(
            gen_ai_model_provider=self.llm_config.model_provider,
            gen_ai_model_version_override=self.llm_config.model_version,
            timeout=timeout,
            temperature=self.llm_config.temperature,
        )
        self.llm_tokenizer = get_default_llm_tokenizer()

        self._final_prompt: list[BaseMessage] | None = None

        self._pruned_docs: list[LlmDoc] | None = None

        self._streamed_output: list[str] | None = None
        self._processed_stream: list[AnswerQuestionPossibleReturn] | None = None

    @property
    def pruned_docs(self) -> list[LlmDoc]:
        if self._pruned_docs is not None:
            return self._pruned_docs

        self._pruned_docs = prune_documents(
            docs=self.docs,
            doc_relevance_list=self.doc_relevance_list,
            prompt_config=self.prompt_config,
            llm_config=self.llm_config,
            question=self.question,
            document_pruning_config=self.answer_style_config.document_pruning_config,
        )
        return self._pruned_docs

    @property
    def final_prompt(self) -> list[BaseMessage]:
        if self._final_prompt is not None:
            return self._final_prompt

        if self.answer_style_config.citation_config:
            self._final_prompt = build_citations_prompt(
                question=self.question,
                message_history=self.message_history,
                llm_config=self.llm_config,
                prompt_config=self.prompt_config,
                context_docs=self.pruned_docs,
                all_doc_useful=self.answer_style_config.citation_config.all_docs_useful,
                llm_tokenizer_encode_func=self.llm_tokenizer.encode,
                history_message=self.single_message_history or "",
            )
        elif self.answer_style_config.quotes_config:
            self._final_prompt = build_quotes_prompt(
                question=self.question,
                context_docs=self.pruned_docs,
                history_str=self.single_message_history or "",
                prompt=self.prompt_config,
            )

        return cast(list[BaseMessage], self._final_prompt)

    @property
    def raw_streamed_output(self) -> Iterator[str]:
        if self._streamed_output is not None:
            yield from self._streamed_output
            return

        streamed_output = []
        for message in self.llm.stream(self.final_prompt):
            streamed_output.append(message)
            yield message

        self._streamed_output = streamed_output

    @property
    def processed_streamed_output(self) -> AnswerQuestionStreamReturn:
        if self._processed_stream is not None:
            yield from self._processed_stream
            return

        process_stream_fn = _get_stream_processor(
            context_docs=self.pruned_docs,
            search_order_docs=self.docs,
            answer_style_configs=self.answer_style_config,
        )

        processed_stream = []
        for processed_packet in process_stream_fn(self.raw_streamed_output):
            processed_stream.append(processed_packet)
            yield processed_packet

        self._processed_stream = processed_stream

    @property
    def llm_answer(self) -> str:
        answer = ""
        for packet in self.processed_streamed_output:
            if isinstance(packet, DanswerAnswerPiece) and packet.answer_piece:
                answer += packet.answer_piece

        return answer

    @property
    def citations(self) -> list[CitationInfo]:
        citations: list[CitationInfo] = []
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo):
                citations.append(packet)

        return citations
