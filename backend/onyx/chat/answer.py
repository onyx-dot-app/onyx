from collections import defaultdict
from collections.abc import Callable

from langchain.schema.messages import BaseMessage
from sqlalchemy.orm import Session

from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.run_graph import run_basic_graph
from onyx.agents.agent_search.run_graph import run_main_graph
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import AnswerPacket
from onyx.chat.models import AnswerStream
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationInfo
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import PromptConfig
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.tool_handling.tool_response_handler import get_tool_by_name
from onyx.configs.constants import BASIC_KEY
from onyx.file_store.utils import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool
from onyx.tools.utils import explicit_tool_calling_supported
from onyx.utils.logger import setup_logger

logger = setup_logger()


class Answer:
    def __init__(
        self,
        question: str,
        answer_style_config: AnswerStyleConfig,
        llm: LLM,
        prompt_config: PromptConfig,
        force_use_tool: ForceUseTool,
        agent_search_config: AgentSearchConfig,
        # must be the same length as `docs`. If None, all docs are considered "relevant"
        message_history: list[PreviousMessage] | None = None,
        single_message_history: str | None = None,
        # newly passed in files to include as part of this question
        # TODO THIS NEEDS TO BE HANDLED
        latest_query_files: list[InMemoryChatFile] | None = None,
        tools: list[Tool] | None = None,
        # NOTE: for native tool-calling, this is only supported by OpenAI atm,
        #       but we only support them anyways
        # if set to True, then never use the LLMs provided tool-calling functonality
        skip_explicit_tool_calling: bool = False,
        skip_gen_ai_answer_generation: bool = False,
        is_connected: Callable[[], bool] | None = None,
        fast_llm: LLM | None = None,
        db_session: Session | None = None,
    ) -> None:
        if single_message_history and message_history:
            raise ValueError(
                "Cannot provide both `message_history` and `single_message_history`"
            )

        self.question = question
        self.is_connected: Callable[[], bool] | None = is_connected

        self.latest_query_files = latest_query_files or []

        self.tools = tools or []
        self.force_use_tool = force_use_tool

        self.message_history = message_history or []
        # used for QA flow where we only want to send a single message
        self.single_message_history = single_message_history

        self.answer_style_config = answer_style_config
        self.prompt_config = prompt_config

        self.llm = llm
        self.fast_llm = fast_llm
        self.llm_tokenizer = get_tokenizer(
            provider_type=llm.config.model_provider,
            model_name=llm.config.model_name,
        )

        self._final_prompt: list[BaseMessage] | None = None

        self._streamed_output: list[str] | None = None
        self._processed_stream: (list[AnswerPacket] | None) = None

        self.skip_gen_ai_answer_generation = skip_gen_ai_answer_generation
        self._is_cancelled = False

        self.using_tool_calling_llm = (
            explicit_tool_calling_supported(
                self.llm.config.model_provider, self.llm.config.model_name
            )
            and not skip_explicit_tool_calling
        )

        self.agent_search_config = agent_search_config
        self.db_session = db_session

    def _get_tools_list(self) -> list[Tool]:
        if not self.force_use_tool.force_use:
            return self.tools

        tool = get_tool_by_name(self.tools, self.force_use_tool.tool_name)

        args_str = (
            f" with args='{self.force_use_tool.args}'"
            if self.force_use_tool.args
            else ""
        )
        logger.info(f"Forcefully using tool='{tool.name}'{args_str}")
        return [tool]

    # TODO: delete the function and move the full body to processed_streamed_output
    def _get_response(self) -> AnswerStream:
        # current_llm_call = llm_calls[-1]

        # tool, tool_args = None, None
        # # handle the case where no decision has to be made; we simply run the tool
        # if (
        #     current_llm_call.force_use_tool.force_use
        #     and current_llm_call.force_use_tool.args is not None
        # ):
        #     tool_name, tool_args = (
        #         current_llm_call.force_use_tool.tool_name,
        #         current_llm_call.force_use_tool.args,
        #     )
        #     tool = get_tool_by_name(current_llm_call.tools, tool_name)

        # # special pre-logic for non-tool calling LLM case
        # elif not self.using_tool_calling_llm and current_llm_call.tools:
        #     chosen_tool_and_args = (
        #         ToolResponseHandler.get_tool_call_for_non_tool_calling_llm(
        #             current_llm_call, self.llm
        #         )
        #     )
        #     if chosen_tool_and_args:
        #         tool, tool_args = chosen_tool_and_args

        # if tool and tool_args:
        #     dummy_tool_call_chunk = AIMessageChunk(content="")
        #     dummy_tool_call_chunk.tool_calls = [
        #         ToolCall(name=tool.name, args=tool_args, id=str(uuid4()))
        #     ]

        #     response_handler_manager = LLMResponseHandlerManager(
        #         ToolResponseHandler([tool]), None, self.is_cancelled
        #     )
        #     yield from response_handler_manager.handle_llm_response(
        #         iter([dummy_tool_call_chunk])
        #     )

        #     tmp_call = response_handler_manager.next_llm_call(current_llm_call)
        #     if tmp_call is None:
        #         return  # no more LLM calls to process
        #     current_llm_call = tmp_call

        # # if we're skipping gen ai answer generation, we should break
        # # out unless we're forcing a tool call. If we don't, we might generate an
        # # answer, which is a no-no!
        # if (
        #     self.skip_gen_ai_answer_generation
        #     and not current_llm_call.force_use_tool.force_use
        # ):
        #     return

        # # set up "handlers" to listen to the LLM response stream and
        # # feed back the processed results + handle tool call requests
        # # + figure out what the next LLM call should be
        # tool_call_handler = ToolResponseHandler(current_llm_call.tools)

        # final_search_results, displayed_search_results = SearchTool.get_search_result(
        #     current_llm_call
        # ) or ([], [])

        # # NEXT: we still want to handle the LLM response stream, but it is now:
        # # 1. handle the tool call requests
        # # 2. feed back the processed results
        # # 3. handle the citations

        # answer_handler = CitationResponseHandler(
        #     context_docs=final_search_results,
        #     final_doc_id_to_rank_map=map_document_id_order(final_search_results),
        #     display_doc_id_to_rank_map=map_document_id_order(displayed_search_results),
        # )

        # # At the moment, this wrapper class passes streamed stuff through citation and tool handlers.
        # # In the future, we'll want to handle citations and tool calls in the langgraph graph.
        # response_handler_manager = LLMResponseHandlerManager(
        #     tool_call_handler, answer_handler, self.is_cancelled
        # )

        # In langgraph, whether we do the basic thing (call llm stream) or pro search
        # is based on a flag in the pro search config

        if self.agent_search_config.use_agentic_search:
            if (
                self.agent_search_config.db_session is None
                and self.agent_search_config.use_persistence
            ):
                raise ValueError(
                    "db_session must be provided for pro search when using persistence"
                )

            stream = run_main_graph(
                config=self.agent_search_config,
            )
        else:
            stream = run_basic_graph(
                config=self.agent_search_config,
            )

        processed_stream = []
        for packet in stream:
            if self.is_cancelled():
                packet = StreamStopInfo(stop_reason=StreamStopReason.CANCELLED)
                yield packet
                break
            processed_stream.append(packet)
            yield packet
        self._processed_stream = processed_stream
        return
        # DEBUG: good breakpoint
        # stream = self.llm.stream(
        #     # For tool calling LLMs, we want to insert the task prompt as part of this flow, this is because the LLM
        #     # may choose to not call any tools and just generate the answer, in which case the task prompt is needed.
        #     prompt=current_llm_call.prompt_builder.build(),
        #     tools=[tool.tool_definition() for tool in current_llm_call.tools] or None,
        #     tool_choice=(
        #         "required"
        #         if current_llm_call.tools and current_llm_call.force_use_tool.force_use
        #         else None
        #     ),
        #     structured_response_format=self.answer_style_config.structured_response_format,
        # )
        # yield from response_handler_manager.handle_llm_response(stream)

        # new_llm_call = response_handler_manager.next_llm_call(current_llm_call)
        # if new_llm_call:
        #     yield from self._get_response(llm_calls + [new_llm_call])

    @property
    def processed_streamed_output(self) -> AnswerStream:
        if self._processed_stream is not None:
            yield from self._processed_stream
            return

        # prompt_builder = AnswerPromptBuilder(
        #     user_message=default_build_user_message(
        #         user_query=self.question,
        #         prompt_config=self.prompt_config,
        #         files=self.latest_query_files,
        #         single_message_history=self.single_message_history,
        #     ),
        #     message_history=self.message_history,
        #     llm_config=self.llm.config,
        #     raw_user_query=self.question,
        #     raw_user_uploaded_files=self.latest_query_files or [],
        #     single_message_history=self.single_message_history,
        # )
        # prompt_builder.update_system_prompt(
        #     default_build_system_message(self.prompt_config)
        # )
        # llm_call = LLMCall(
        #     prompt_builder=prompt_builder,
        #     tools=self._get_tools_list(),
        #     force_use_tool=self.force_use_tool,
        #     files=self.latest_query_files,
        #     tool_call_info=[],
        #     using_tool_calling_llm=self.using_tool_calling_llm,
        # )

        processed_stream = []
        for processed_packet in self._get_response():
            processed_stream.append(processed_packet)
            yield processed_packet

        self._processed_stream = processed_stream

    @property
    def llm_answer(self) -> str:
        answer = ""
        for packet in self.processed_streamed_output:
            # handle basic answer flow, plus level 0 agent answer flow
            # since level 0 is the first answer the user sees and therefore the
            # child message of the user message in the db (so it is handled
            # like a basic flow answer)
            if (isinstance(packet, OnyxAnswerPiece) and packet.answer_piece) or (
                isinstance(packet, AgentAnswerPiece)
                and packet.answer_piece
                and packet.answer_type == "agent_level_answer"
                and packet.level == 0
            ):
                answer += packet.answer_piece

        return answer

    def llm_answer_by_level(self) -> dict[int, str]:
        answer_by_level: dict[int, str] = defaultdict(str)
        for packet in self.processed_streamed_output:
            if (
                isinstance(packet, AgentAnswerPiece)
                and packet.answer_piece
                and packet.answer_type == "agent_level_answer"
            ):
                answer_by_level[packet.level] += packet.answer_piece
            elif isinstance(packet, OnyxAnswerPiece) and packet.answer_piece:
                answer_by_level[BASIC_KEY[0]] += packet.answer_piece
        return answer_by_level

    @property
    def citations(self) -> list[CitationInfo]:
        citations: list[CitationInfo] = []
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo) and packet.level is None:
                citations.append(packet)

        return citations

    def citations_by_subquestion(self) -> dict[tuple[int, int], list[CitationInfo]]:
        citations_by_subquestion: dict[
            tuple[int, int], list[CitationInfo]
        ] = defaultdict(list)
        for packet in self.processed_streamed_output:
            if isinstance(packet, CitationInfo):
                if packet.level_question_nr is not None and packet.level is not None:
                    citations_by_subquestion[
                        (packet.level, packet.level_question_nr)
                    ].append(packet)
                elif packet.level is None:
                    citations_by_subquestion[BASIC_KEY].append(packet)
        return citations_by_subquestion

    def is_cancelled(self) -> bool:
        if self._is_cancelled:
            return True

        if self.is_connected is not None:
            if not self.is_connected():
                logger.debug("Answer stream has been cancelled")
            self._is_cancelled = not self.is_connected()

        return self._is_cancelled
