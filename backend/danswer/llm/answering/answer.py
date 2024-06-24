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
from danswer.llm.interfaces import LLM
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.llm.utils import message_generator_to_string_generator
from danswer.tools.custom.custom_tool_prompt_builder import (
    build_user_message_for_custom_tool_for_non_tool_calling_llm,
)
from danswer.tools.force import filter_tools_for_force_tool_use
from danswer.tools.force import ForceUseTool
from danswer.tools.images.image_generation_tool import IMAGE_GENERATION_RESPONSE_ID
from danswer.tools.images.image_generation_tool import ImageGenerationResponse
from danswer.tools.images.image_generation_tool import ImageGenerationTool
from danswer.tools.images.prompt import build_image_generation_user_prompt
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
from danswer.tools.utils import explicit_tool_calling_supported


def _get_answer_stream_processor(
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


AnswerStream = Iterator[AnswerQuestionPossibleReturn | ToolCallKickoff | ToolResponse]


class Answer:
    def __init__(
        self,
        question: str,
        answer_style_config: AnswerStyleConfig,
        llm: LLM,
        prompt_config: PromptConfig,
        # must be the same length as `docs`. If None, all docs are considered "relevant"
        message_history: list[PreviousMessage] | None = None,
        single_message_history: str | None = None,
        # newly passed in files to include as part of this question
        # TODO THIS NEEDS TO BE HANDLED
        latest_query_files: list[InMemoryChatFile] | None = None,
        files: list[InMemoryChatFile] | None = None,
        tools: list[Tool] | None = None,
        # if specified, tells the LLM to always this tool
        # NOTE: for native tool-calling, this is only supported by OpenAI atm,
        #       but we only support them anyways
        force_use_tool: ForceUseTool | None = None,
        # if set to True, then never use the LLMs provided tool-calling functonality
        skip_explicit_tool_calling: bool = False,
        # Returns the full document sections text from the search tool
        return_contexts: bool = False,
    ) -> None:
        if single_message_history and message_history:
            raise ValueError(
                "Cannot provide both `message_history` and `single_message_history`"
            )

        self.question = question

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
        self.llm_tokenizer = get_default_llm_tokenizer()

        self._final_prompt: list[BaseMessage] | None = None

        self._streamed_output: list[str] | None = None
        self._processed_stream: list[
            AnswerQuestionPossibleReturn | ToolResponse | ToolCallKickoff
        ] | None = None

        self._return_contexts = return_contexts

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
        if self.force_use_tool and self.force_use_tool.args is not None:
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
                tool_choice="required" if self.force_use_tool else None,
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
                        yield cast(str, message.content)

            if not tool_call_chunk:
                return  # no tool call needed

        # if we have a tool call, we need to call the tool
        tool_call_requests = tool_call_chunk.tool_calls
        for tool_call_request in tool_call_requests:
            tool = [
                tool for tool in self.tools if tool.name() == tool_call_request["name"]
            ][0]
            tool_args = (
                self.force_use_tool.args
                if self.force_use_tool and self.force_use_tool.args
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

            if tool.name() == SearchTool.NAME:
                self._update_prompt_builder_for_search_tool(prompt_builder, [])
            elif tool.name() == ImageGenerationTool.NAME:
                prompt_builder.update_user_prompt(
                    build_image_generation_user_prompt(
                        query=self.question,
                    )
                )

            yield tool_runner.tool_final_result()

            prompt = prompt_builder.build(tool_call_summary=tool_call_summary)
            yield from message_generator_to_string_generator(
                self.llm.stream(
                    prompt=prompt,
                    tools=[tool.tool_definition() for tool in self.tools],
                )
            )

            return

    def _raw_output_for_non_explicit_tool_calling_llms(
        self,
    ) -> Iterator[str | ToolCallKickoff | ToolResponse | ToolCallFinalResult]:
        prompt_builder = AnswerPromptBuilder(self.message_history, self.llm.config)
        chosen_tool_and_args: tuple[Tool, dict] | None = None

        if self.force_use_tool:
            # if we are forcing a tool, we don't need to check which tools to run
            tool = next(
                iter(
                    [
                        tool
                        for tool in self.tools
                        if tool.name() == self.force_use_tool.tool_name
                    ]
                ),
                None,
            )
            if not tool:
                raise RuntimeError(f"Tool '{self.force_use_tool.tool_name}' not found")

            tool_args = (
                self.force_use_tool.args
                if self.force_use_tool.args
                else tool.get_args_for_non_tool_calling_llm(
                    query=self.question,
                    history=self.message_history,
                    llm=self.llm,
                    force_run=True,
                )
            )

            if tool_args is None:
                raise RuntimeError(f"Tool '{tool.name()}' did not return args")

            chosen_tool_and_args = (tool, tool_args)
        else:
            all_tool_args = check_which_tools_should_run_for_non_tool_calling_llm(
                tools=self.tools,
                query=self.question,
                history=self.message_history,
                llm=self.llm,
            )
            for ind, args in enumerate(all_tool_args):
                if args is not None:
                    chosen_tool_and_args = (self.tools[ind], args)
                    # for now, just pick the first tool selected
                    break

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
            yield from message_generator_to_string_generator(
                self.llm.stream(prompt=prompt)
            )
            return

        tool, tool_args = chosen_tool_and_args
        tool_runner = ToolRunner(tool, tool_args)
        yield tool_runner.kickoff()

        if tool.name() == SearchTool.NAME:
            final_context_documents = None
            for response in tool_runner.tool_responses():
                if response.id == FINAL_CONTEXT_DOCUMENTS:
                    final_context_documents = cast(list[LlmDoc], response.response)
                yield response

            if final_context_documents is None:
                raise RuntimeError("SearchTool did not return final context documents")

            self._update_prompt_builder_for_search_tool(
                prompt_builder, final_context_documents
            )
        elif tool.name() == ImageGenerationTool.NAME:
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
                        tool.name(),
                        *tool_runner.tool_responses(),
                    )
                )
            )

        yield tool_runner.tool_final_result()

        prompt = prompt_builder.build()
        yield from message_generator_to_string_generator(self.llm.stream(prompt=prompt))

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

            process_answer_stream_fn = _get_answer_stream_processor(
                context_docs=final_context_docs or [],
                # if doc selection is enabled, then search_results will be None,
                # so we need to use the final_context_docs
                search_order_docs=search_results or final_context_docs or [],
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
