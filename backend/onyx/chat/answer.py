from collections.abc import Callable
from collections.abc import Iterator
from uuid import uuid4

from langchain.schema.messages import BaseMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import ToolCall

from onyx.chat.llm_response_handler import LLMResponseHandlerManager
from onyx.chat.models import AnswerQuestionPossibleReturn
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationInfo
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.build import AnswerPromptBuilder
from onyx.chat.prompt_builder.build import default_build_system_message
from onyx.chat.prompt_builder.build import default_build_user_message
from onyx.chat.prompt_builder.build import LLMCall
from onyx.chat.stream_processing.answer_response_handler import (
    CitationResponseHandler,
)
from onyx.chat.stream_processing.answer_response_handler import (
    DummyAnswerResponseHandler,
)
from onyx.chat.stream_processing.utils import (
    map_document_id_order,
)
from onyx.chat.tool_handling.tool_response_handler import ToolResponseHandler
from onyx.file_store.utils import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.force import ForceUseTool
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_runner import ToolCallKickoff
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.logger import setup_logger


logger = setup_logger()


AnswerStream = Iterator[AnswerQuestionPossibleReturn | ToolCallKickoff | ToolResponse]


class Answer:
    def __init__(
        self,
        question: str,
        answer_style_config: AnswerStyleConfig,
        llm: LLM,
        prompt_config: PromptConfig,
        force_use_tool: ForceUseTool,
        # must be the same length as `docs`. If None, all docs are considered "relevant"
        message_history: list[PreviousMessage] | None = None,
        single_message_history: str | None = None,
        # newly passed in files to include as part of this question
        # TODO THIS NEEDS TO BE HANDLED
        latest_query_files: list[InMemoryChatFile] | None = None,
        files: list[InMemoryChatFile] | None = None,
        tools: list[Tool] | None = None,
        # NOTE: for native tool-calling, this is only supported by OpenAI atm,
        #       but we only support them anyways
        # if set to True, then never use the LLMs provided tool-calling functonality
        skip_explicit_tool_calling: bool = False,
        # Returns the full document sections text from the search tool
        return_contexts: bool = False,
        skip_gen_ai_answer_generation: bool = False,
        is_connected: Callable[[], bool] | None = None,
    ) -> None:
        if single_message_history and message_history:
            raise ValueError(
                "Cannot provide both `message_history` and `single_message_history`"
            )

        self.question = question
        self.is_connected: Callable[[], bool] | None = is_connected

        self.latest_query_files = latest_query_files or []
        self.file_id_to_file = {file.file_id: file for file in (files or [])}

        self.tools = tools or []
        self.force_use_tool = force_use_tool

        self.message_history = message_history or []
        # used for QA flow where we only want to send a single message
        self.single_message_history = single_message_history

        self.answer_style_config = answer_style_config
        self.prompt_config = prompt_config

        self.llm = llm
        self.llm_tokenizer = get_tokenizer(
            provider_type=llm.config.model_provider,
            model_name=llm.config.model_name,
        )

        self._final_prompt: list[BaseMessage] | None = None

        self._streamed_output: list[str] | None = None
        self._processed_stream: (
            list[AnswerQuestionPossibleReturn | ToolResponse | ToolCallKickoff] | None
        ) = None

        self._return_contexts = return_contexts
        self.skip_gen_ai_answer_generation = skip_gen_ai_answer_generation
        self._is_cancelled = False

        self.using_tool_calling_llm = (
            explicit_tool_calling_supported(
                self.llm.config.model_provider, self.llm.config.model_name
            )
            and not skip_explicit_tool_calling
        )

    def _get_tools_list(self) -> list[Tool]:
        if not self.force_use_tool.force_use:
            return self.tools

        tool = next(
            (t for t in self.tools if t.name == self.force_use_tool.tool_name), None
        )
        if tool is None:
            raise RuntimeError(f"Tool '{self.force_use_tool.tool_name}' not found")

        logger.info(
            f"Forcefully using tool='{tool.name}'"
            + (
                f" with args='{self.force_use_tool.args}'"
                if self.force_use_tool.args is not None
                else ""
            )
        )
        return [tool]

    def _handle_specified_tool_call(
        self, llm_calls: list[LLMCall], tool: Tool, tool_args: dict
    ) -> AnswerStream:
        current_llm_call = llm_calls[-1]

        # make a dummy tool handler
        tool_handler = ToolResponseHandler([tool])

        dummy_tool_call_chunk = AIMessageChunk(content="")
        dummy_tool_call_chunk.tool_calls = [
            ToolCall(name=tool.name, args=tool_args, id=str(uuid4()))
        ]

        response_handler_manager = LLMResponseHandlerManager(
            tool_handler, DummyAnswerResponseHandler(), self.is_cancelled
        )
        yield from response_handler_manager.handle_llm_response(
            iter([dummy_tool_call_chunk])
        )

        new_llm_call = response_handler_manager.next_llm_call(current_llm_call)
        if new_llm_call:
            yield from self._get_response(llm_calls + [new_llm_call])
        else:
            raise RuntimeError("Tool call handler did not return a new LLM call")

    def _get_response(self, llm_calls: list[LLMCall]) -> AnswerStream:
        current_llm_call = llm_calls[-1]

        # handle the case where no decision has to be made; we simply run the tool
        if (
            current_llm_call.force_use_tool.force_use
            and current_llm_call.force_use_tool.args is not None
        ):
            tool_name, tool_args = (
                current_llm_call.force_use_tool.tool_name,
                current_llm_call.force_use_tool.args,
            )
            tool = next(
                (t for t in current_llm_call.tools if t.name == tool_name), None
            )
            if not tool:
                raise RuntimeError(f"Tool '{tool_name}' not found")

            yield from self._handle_specified_tool_call(llm_calls, tool, tool_args)
            return

        # special pre-logic for non-tool calling LLM case
        if not self.using_tool_calling_llm and current_llm_call.tools:
            chosen_tool_and_args = (
                ToolResponseHandler.get_tool_call_for_non_tool_calling_llm(
                    current_llm_call, self.llm
                )
            )
            if chosen_tool_and_args:
                tool, tool_args = chosen_tool_and_args
                yield from self._handle_specified_tool_call(llm_calls, tool, tool_args)
                return

        # if we're skipping gen ai answer generation, we should break
        # out unless we're forcing a tool call. If we don't, we might generate an
        # answer, which is a no-no!
        if (
            self.skip_gen_ai_answer_generation
            and not current_llm_call.force_use_tool.force_use
        ):
            return

        # set up "handlers" to listen to the LLM response stream and
        # feed back the processed results + handle tool call requests
        # + figure out what the next LLM call should be
        tool_call_handler = ToolResponseHandler(current_llm_call.tools)

        final_search_results, displayed_search_results = SearchTool.get_search_result(
            current_llm_call
        ) or ([], [])

        # Quotes are no longer supported
        # answer_handler: AnswerResponseHandler
        # if self.answer_style_config.citation_config:
        #     answer_handler = CitationResponseHandler(
        #         context_docs=search_result,
        #         doc_id_to_rank_map=map_document_id_order(search_result),
        #     )
        # elif self.answer_style_config.quotes_config:
        #     answer_handler = QuotesResponseHandler(
        #         context_docs=search_result,
        #     )
        # else:
        #     raise ValueError("No answer style config provided")
        answer_handler = CitationResponseHandler(
            context_docs=final_search_results,
            final_doc_id_to_rank_map=map_document_id_order(final_search_results),
            display_doc_id_to_rank_map=map_document_id_order(displayed_search_results),
        )

        response_handler_manager = LLMResponseHandlerManager(
            tool_call_handler, answer_handler, self.is_cancelled
        )

        # DEBUG: good breakpoint
        stream = self.llm.stream(
            # For tool calling LLMs, we want to insert the task prompt as part of this flow, this is because the LLM
            # may choose to not call any tools and just generate the answer, in which case the task prompt is needed.
            prompt=current_llm_call.prompt_builder.build(),
            tools=[tool.tool_definition() for tool in current_llm_call.tools] or None,
            tool_choice=(
                "required"
                if current_llm_call.tools and current_llm_call.force_use_tool.force_use
                else None
            ),
            structured_response_format=self.answer_style_config.structured_response_format,
        )
        yield from response_handler_manager.handle_llm_response(stream)

        new_llm_call = response_handler_manager.next_llm_call(current_llm_call)
        if new_llm_call:
            yield from self._get_response(llm_calls + [new_llm_call])

    @property
    def processed_streamed_output(self) -> AnswerStream:
        if self._processed_stream is not None:
            yield from self._processed_stream
            return

        prompt_builder = AnswerPromptBuilder(
            user_message=default_build_user_message(
                user_query=self.question,
                prompt_config=self.prompt_config,
                files=self.latest_query_files,
            ),
            message_history=self.message_history,
            llm_config=self.llm.config,
            single_message_history=self.single_message_history,
            raw_user_text=self.question,
        )
        prompt_builder.update_system_prompt(
            default_build_system_message(self.prompt_config)
        )
        llm_call = LLMCall(
            prompt_builder=prompt_builder,
            tools=self._get_tools_list(),
            force_use_tool=self.force_use_tool,
            files=self.latest_query_files,
            tool_call_info=[],
            using_tool_calling_llm=self.using_tool_calling_llm,
        )

        processed_stream = []
        for processed_packet in self._get_response([llm_call]):
            processed_stream.append(processed_packet)
            yield processed_packet

        self._processed_stream = processed_stream

    @property
    def llm_answer(self) -> str:
        answer = ""
        for packet in self.processed_streamed_output:
            if isinstance(packet, OnyxAnswerPiece) and packet.answer_piece:
                answer += packet.answer_piece

        return answer

    @property
    def citations(self) -> list[CitationInfo]:
        citations: list[CitationInfo] = []
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo):
                citations.append(packet)

        return citations

    def is_cancelled(self) -> bool:
        if self._is_cancelled:
            return True

        if self.is_connected is not None:
            if not self.is_connected():
                logger.debug("Answer stream has been cancelled")
            self._is_cancelled = not self.is_connected()

        return self._is_cancelled
