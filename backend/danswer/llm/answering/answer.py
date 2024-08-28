from collections.abc import Callable
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

from langchain.schema.messages import BaseMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import HumanMessage

from danswer.chat.chat_utils import llm_doc_from_inference_section
from danswer.chat.models import AnswerQuestionPossibleReturn
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import QA_PROMPT_OVERRIDE
from danswer.file_store.utils import InMemoryChatFile
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.models import StreamProcessor
from danswer.llm.answering.prompts.build import AnswerPromptBuilder
from danswer.llm.answering.prompts.build import default_build_system_message
from danswer.llm.answering.prompts.build import default_build_user_message
from danswer.llm.answering.prompts.citations_prompt import (
    build_citations_system_message,
)
from danswer.llm.answering.prompts.citations_prompt import build_citations_user_message
from danswer.llm.answering.prompts.quotes_prompt import build_quotes_user_message
from danswer.llm.answering.stream_processing.citation_processing import (
    build_citation_processor,
)
from danswer.llm.answering.stream_processing.quotes_processing import (
    build_quotes_processor,
)
from danswer.llm.answering.stream_processing.utils import DocumentIdOrderMapping
from danswer.llm.answering.stream_processing.utils import map_document_id_order
from danswer.llm.interfaces import LLM
from danswer.llm.utils import message_generator_to_string_generator
from danswer.natural_language_processing.utils import get_tokenizer
from danswer.tools.custom.custom_tool_prompt_builder import (
    build_user_message_for_custom_tool_for_non_tool_calling_llm,
)
from danswer.tools.force import filter_tools_for_force_tool_use
from danswer.tools.force import ForceUseTool
from danswer.tools.images.image_generation_tool import IMAGE_GENERATION_RESPONSE_ID
from danswer.tools.images.image_generation_tool import ImageGenerationResponse
from danswer.tools.images.image_generation_tool import ImageGenerationTool
from danswer.tools.images.prompt import build_image_generation_user_prompt
from danswer.tools.internet_search.internet_search_tool import InternetSearchTool
from danswer.tools.message import build_tool_message
from danswer.tools.message import ToolCallSummary
from danswer.tools.search.search_tool import FINAL_CONTEXT_DOCUMENTS
from danswer.tools.search.search_tool import SEARCH_DOC_CONTENT_ID
from danswer.tools.search.search_tool import SEARCH_RESPONSE_SUMMARY_ID
from danswer.tools.search.search_tool import SearchResponseSummary
from danswer.tools.search.search_tool import SearchTool
from danswer.tools.tool import Tool
from danswer.tools.tool import ToolResponse
from danswer.tools.tool_runner import (
    check_which_tools_should_run_for_non_tool_calling_llm,
)
from danswer.tools.tool_runner import ToolCallFinalResult
from danswer.tools.tool_runner import ToolCallKickoff
from danswer.tools.tool_runner import ToolRunner
from danswer.tools.tool_selection import select_single_tool_for_non_tool_calling_llm
from danswer.tools.utils import explicit_tool_calling_supported
from danswer.utils.logger import setup_logger


logger = setup_logger()


def _get_answer_stream_processor(
    context_docs: list[LlmDoc],
    doc_id_to_rank_map: DocumentIdOrderMapping,
    answer_style_configs: AnswerStyleConfig,
) -> StreamProcessor:
    if answer_style_configs.citation_config:
        return build_citation_processor(
            context_docs=context_docs, doc_id_to_rank_map=doc_id_to_rank_map
        )
    if answer_style_configs.quotes_config:
        return build_quotes_processor(
            context_docs=context_docs, is_json_prompt=not (QA_PROMPT_OVERRIDE == "weak")
        )

    raise RuntimeError("Not implemented yet")


AnswerStream = Iterator[AnswerQuestionPossibleReturn | ToolCallKickoff | ToolResponse]


logger = setup_logger()


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

        self.skip_explicit_tool_calling = skip_explicit_tool_calling

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

    def _update_prompt_builder_for_search_tool(
        self, prompt_builder: AnswerPromptBuilder, final_context_documents: list[LlmDoc]
    ) -> None:
        if self.answer_style_config.citation_config:
            prompt_builder.update_system_prompt(
                build_citations_system_message(self.prompt_config)
            )
            prompt_builder.update_user_prompt(
                build_citations_user_message(
                    question=self.question,
                    prompt_config=self.prompt_config,
                    context_docs=final_context_documents,
                    files=self.latest_query_files,
                    all_doc_useful=(
                        self.answer_style_config.citation_config.all_docs_useful
                        if self.answer_style_config.citation_config
                        else False
                    ),
                )
            )
        elif self.answer_style_config.quotes_config:
            prompt_builder.update_user_prompt(
                build_quotes_user_message(
                    question=self.question,
                    context_docs=final_context_documents,
                    history_str=self.single_message_history or "",
                    prompt=self.prompt_config,
                )
            )

    def _raw_output_for_explicit_tool_calling_llms(
        self,
    ) -> Iterator[str | ToolCallKickoff | ToolResponse | ToolCallFinalResult]:
        prompt_builder = AnswerPromptBuilder(self.message_history, self.llm.config)

        tool_call_chunk: AIMessageChunk | None = None
        if self.force_use_tool.force_use and self.force_use_tool.args is not None:
            # if we are forcing a tool WITH args specified, we don't need to check which tools to run
            # / need to generate the args
            tool_call_chunk = AIMessageChunk(
                content="",
            )
            tool_call_chunk.tool_calls = [
                {
                    "name": self.force_use_tool.tool_name,
                    "args": self.force_use_tool.args,
                    "id": str(uuid4()),
                }
            ]
        else:
            # if tool calling is supported, first try the raw message
            # to see if we don't need to use any tools
            prompt_builder.update_system_prompt(
                default_build_system_message(self.prompt_config)
            )
            prompt_builder.update_user_prompt(
                default_build_user_message(
                    self.question, self.prompt_config, self.latest_query_files
                )
            )
            prompt = prompt_builder.build()
            final_tool_definitions = [
                tool.tool_definition()
                for tool in filter_tools_for_force_tool_use(
                    self.tools, self.force_use_tool
                )
            ]
            for message in self.llm.stream(
                prompt=prompt,
                tools=final_tool_definitions if final_tool_definitions else None,
                tool_choice="required" if self.force_use_tool.force_use else None,
            ):
                if isinstance(message, AIMessageChunk) and (
                    message.tool_call_chunks or message.tool_calls
                ):
                    if tool_call_chunk is None:
                        tool_call_chunk = message
                    else:
                        tool_call_chunk += message  # type: ignore
                else:
                    if message.content:
                        if self.is_cancelled:
                            return
                        yield cast(str, message.content)

            if not tool_call_chunk:
                return  # no tool call needed

        # if we have a tool call, we need to call the tool
        tool_call_requests = tool_call_chunk.tool_calls
        for tool_call_request in tool_call_requests:
            known_tools_by_name = [
                tool for tool in self.tools if tool.name == tool_call_request["name"]
            ]

            if not known_tools_by_name:
                logger.error(
                    "Tool call requested with unknown name field. \n"
                    f"self.tools: {self.tools}"
                    f"tool_call_request: {tool_call_request}"
                )
                if self.tools:
                    tool = self.tools[0]
                else:
                    continue
            else:
                tool = known_tools_by_name[0]
            tool_args = (
                self.force_use_tool.args
                if self.force_use_tool.tool_name == tool.name
                and self.force_use_tool.args
                else tool_call_request["args"]
            )

            tool_runner = ToolRunner(tool, tool_args)
            yield tool_runner.kickoff()
            yield from tool_runner.tool_responses()

            tool_call_summary = ToolCallSummary(
                tool_call_request=tool_call_chunk,
                tool_call_result=build_tool_message(
                    tool_call_request, tool_runner.tool_message_content()
                ),
            )

            if tool.name in {SearchTool._NAME, InternetSearchTool._NAME}:
                self._update_prompt_builder_for_search_tool(prompt_builder, [])
            elif tool.name == ImageGenerationTool._NAME:
                img_urls = [
                    img_generation_result["url"]
                    for img_generation_result in tool_runner.tool_final_result().tool_result
                ]
                prompt_builder.update_user_prompt(
                    build_image_generation_user_prompt(
                        query=self.question, img_urls=img_urls
                    )
                )
            yield tool_runner.tool_final_result()

            prompt = prompt_builder.build(tool_call_summary=tool_call_summary)
            for token in message_generator_to_string_generator(
                self.llm.stream(
                    prompt=prompt,
                    tools=[tool.tool_definition() for tool in self.tools],
                )
            ):
                if self.is_cancelled:
                    return
                yield token

            return

    def _raw_output_for_non_explicit_tool_calling_llms(
        self,
    ) -> Iterator[str | ToolCallKickoff | ToolResponse | ToolCallFinalResult]:
        prompt_builder = AnswerPromptBuilder(self.message_history, self.llm.config)
        chosen_tool_and_args: tuple[Tool, dict] | None = None

        if self.force_use_tool.force_use:
            # if we are forcing a tool, we don't need to check which tools to run
            tool = next(
                iter(
                    [
                        tool
                        for tool in self.tools
                        if tool.name == self.force_use_tool.tool_name
                    ]
                ),
                None,
            )
            if not tool:
                raise RuntimeError(f"Tool '{self.force_use_tool.tool_name}' not found")

            tool_args = (
                self.force_use_tool.args
                if self.force_use_tool.args is not None
                else tool.get_args_for_non_tool_calling_llm(
                    query=self.question,
                    history=self.message_history,
                    llm=self.llm,
                    force_run=True,
                )
            )

            if tool_args is None:
                raise RuntimeError(f"Tool '{tool.name}' did not return args")

            chosen_tool_and_args = (tool, tool_args)
        else:
            tool_options = check_which_tools_should_run_for_non_tool_calling_llm(
                tools=self.tools,
                query=self.question,
                history=self.message_history,
                llm=self.llm,
            )

            available_tools_and_args = [
                (self.tools[ind], args)
                for ind, args in enumerate(tool_options)
                if args is not None
            ]

            logger.info(
                f"Selecting single tool from tools: {[(tool.name, args) for tool, args in available_tools_and_args]}"
            )

            chosen_tool_and_args = (
                select_single_tool_for_non_tool_calling_llm(
                    tools_and_args=available_tools_and_args,
                    history=self.message_history,
                    query=self.question,
                    llm=self.llm,
                )
                if available_tools_and_args
                else None
            )

            logger.notice(f"Chosen tool: {chosen_tool_and_args}")

        if not chosen_tool_and_args:
            prompt_builder.update_system_prompt(
                default_build_system_message(self.prompt_config)
            )
            prompt_builder.update_user_prompt(
                default_build_user_message(
                    self.question, self.prompt_config, self.latest_query_files
                )
            )
            prompt = prompt_builder.build()
            for token in message_generator_to_string_generator(
                self.llm.stream(prompt=prompt)
            ):
                if self.is_cancelled:
                    return
                yield token

            return

        tool, tool_args = chosen_tool_and_args
        tool_runner = ToolRunner(tool, tool_args)
        yield tool_runner.kickoff()

        if tool.name in {SearchTool._NAME, InternetSearchTool._NAME}:
            final_context_documents = None
            for response in tool_runner.tool_responses():
                if response.id == FINAL_CONTEXT_DOCUMENTS:
                    final_context_documents = cast(list[LlmDoc], response.response)
                yield response

            if final_context_documents is None:
                raise RuntimeError(
                    f"{tool.name} did not return final context documents"
                )

            self._update_prompt_builder_for_search_tool(
                prompt_builder, final_context_documents
            )
        elif tool.name == ImageGenerationTool._NAME:
            img_urls = []
            for response in tool_runner.tool_responses():
                if response.id == IMAGE_GENERATION_RESPONSE_ID:
                    img_generation_response = cast(
                        list[ImageGenerationResponse], response.response
                    )
                    img_urls = [img.url for img in img_generation_response]

                yield response

            prompt_builder.update_user_prompt(
                build_image_generation_user_prompt(
                    query=self.question,
                    img_urls=img_urls,
                )
            )
        else:
            prompt_builder.update_user_prompt(
                HumanMessage(
                    content=build_user_message_for_custom_tool_for_non_tool_calling_llm(
                        self.question,
                        tool.name,
                        *tool_runner.tool_responses(),
                    )
                )
            )
        final = tool_runner.tool_final_result()

        yield final

        prompt = prompt_builder.build()
        for token in message_generator_to_string_generator(
            self.llm.stream(prompt=prompt)
        ):
            if self.is_cancelled:
                return
            yield token

    @property
    def processed_streamed_output(self) -> AnswerStream:
        if self._processed_stream is not None:
            yield from self._processed_stream
            return

        output_generator = (
            self._raw_output_for_explicit_tool_calling_llms()
            if explicit_tool_calling_supported(
                self.llm.config.model_provider, self.llm.config.model_name
            )
            and not self.skip_explicit_tool_calling
            else self._raw_output_for_non_explicit_tool_calling_llms()
        )

        def _process_stream(
            stream: Iterator[ToolCallKickoff | ToolResponse | str],
        ) -> AnswerStream:
            message = None

            # special things we need to keep track of for the SearchTool
            search_results: list[
                LlmDoc
            ] | None = None  # raw results that will be displayed to the user
            final_context_docs: list[
                LlmDoc
            ] | None = None  # processed docs to feed into the LLM

            for message in stream:
                if isinstance(message, ToolCallKickoff) or isinstance(
                    message, ToolCallFinalResult
                ):
                    yield message
                elif isinstance(message, ToolResponse):
                    if message.id == SEARCH_RESPONSE_SUMMARY_ID:
                        # We don't need to run section merging in this flow, this variable is only used
                        # below to specify the ordering of the documents for the purpose of matching
                        # citations to the right search documents. The deduplication logic is more lightweight
                        # there and we don't need to do it twice
                        search_results = [
                            llm_doc_from_inference_section(section)
                            for section in cast(
                                SearchResponseSummary, message.response
                            ).top_sections
                        ]
                    elif message.id == FINAL_CONTEXT_DOCUMENTS:
                        final_context_docs = cast(list[LlmDoc], message.response)

                    elif (
                        message.id == SEARCH_DOC_CONTENT_ID
                        and not self._return_contexts
                    ):
                        continue

                    yield message
                else:
                    # assumes all tool responses will come first, then the final answer
                    break

            if not self.skip_gen_ai_answer_generation:
                process_answer_stream_fn = _get_answer_stream_processor(
                    context_docs=final_context_docs or [],
                    # if doc selection is enabled, then search_results will be None,
                    # so we need to use the final_context_docs
                    doc_id_to_rank_map=map_document_id_order(
                        search_results or final_context_docs or []
                    ),
                    answer_style_configs=self.answer_style_config,
                )

                def _stream() -> Iterator[str]:
                    if message:
                        yield cast(str, message)
                    yield from cast(Iterator[str], stream)

                yield from process_answer_stream_fn(_stream())

        processed_stream = []
        for processed_packet in _process_stream(output_generator):
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

    @property
    def is_cancelled(self) -> bool:
        if self._is_cancelled:
            return True

        if self.is_connected is not None:
            if not self.is_connected():
                logger.debug("Answer stream has been cancelled")
            self._is_cancelled = not self.is_connected()

        return self._is_cancelled
