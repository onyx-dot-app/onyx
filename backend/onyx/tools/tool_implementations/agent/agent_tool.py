"""Minimal AgentTool implementation - allows one persona to call another as a tool."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.chat.citation_utils import update_citation_processor_from_tool_response
from onyx.chat.emitter import Emitter
from onyx.chat.llm_step import run_llm_step
from onyx.chat.models import ChatMessageSimple
from onyx.chat.prompt_utils import build_reminder_message, build_system_prompt
from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.db.models import Persona, User
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.factory import get_llm_for_persona
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta, CustomToolStart, Packet
from onyx.tools.interface import Tool, ToolResponse
from onyx.tools.models import AgentCallResult, AgentToolOverrideKwargs, SearchToolUsage, ToolCallException
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_runner import run_tool_calls
from onyx.utils.logger import setup_logger

logger = setup_logger()

AGENT_CYCLE_CAP = 3


class AgentTool(Tool[AgentToolOverrideKwargs | None]):
    """Tool that calls another persona as a sub-agent."""

    NAME = "call_agent"

    def __init__(
        self,
        tool_id: int,
        target_persona: Persona,
        db_session: Session,
        emitter: Emitter,
        user: User | None,
        llm: LLM,
        document_index: DocumentIndex,
        user_selected_filters: BaseFilters | None,
        is_connected_fn: Callable[[], bool] | None = None,
    ):
        super().__init__(emitter=emitter)
        self._id = tool_id
        self.target_persona = target_persona
        self.db_session = db_session
        self.user = user
        self.parent_llm = llm
        self.document_index = document_index
        self.user_selected_filters = user_selected_filters
        self.is_connected_fn = is_connected_fn

        self._display_name = f"Call {target_persona.name}"
        self._tool_name = f"call_{target_persona.name.lower().replace(' ', '_')}"

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def description(self) -> str:
        return f"Delegate a task to {self.target_persona.name}. {self.target_persona.description}"

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The specific task or question to delegate"
                        }
                    },
                    "required": ["task"]
                }
            }
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self.display_name),
            )
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: AgentToolOverrideKwargs | None,
        **kwargs,
    ) -> ToolResponse:
        """Execute sub-agent with the given task."""

        if override_kwargs is None:
            override_kwargs = AgentToolOverrideKwargs()

        # Check recursion
        if self.target_persona.id in override_kwargs.agent_call_stack:
            raise ToolCallException(
                message=f"Recursive call to {self.target_persona.name}",
                llm_facing_message=f"Cannot call {self.target_persona.name} recursively"
            )

        if len(override_kwargs.agent_call_stack) >= override_kwargs.max_recursion_depth:
            raise ToolCallException(
                message=f"Max depth {override_kwargs.max_recursion_depth} exceeded",
                llm_facing_message=f"Maximum delegation depth reached"
            )

        # Extract task from kwargs
        task: str = kwargs.get("task", "")
        if not task:
            raise ToolCallException(
                message="Missing required 'task' parameter",
                llm_facing_message="Please provide a task to delegate"
            )

        # Emit the task being delegated so UI can show it
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self.display_name,
                    response_type="task",
                    data={"task": task, "agent": self.target_persona.name},
                ),
            )
        )

        # Run sub-agent
        result = self._run_sub_agent(
            task=task,
            placement=placement,
            agent_call_stack=override_kwargs.agent_call_stack + [self.target_persona.id],
            starting_citation_num=override_kwargs.starting_citation_num,
            parent_citation_mapping=override_kwargs.citation_mapping,
        )

        # Emit the result so UI can show it
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self.display_name,
                    response_type="result",
                    data={"answer": result.answer, "agent": self.target_persona.name},
                ),
            )
        )

        return ToolResponse(
            rich_response=None,
            llm_facing_response=result.answer,
        )

    def _run_sub_agent(
        self,
        task: str,
        placement: Placement,
        agent_call_stack: list[int],
        starting_citation_num: int,
        parent_citation_mapping: dict[int, str],
    ) -> AgentCallResult:
        """Run sub-agent LLM loop."""

        # FIXME: Local import to avoid circular dependency through built_in_tools

        from onyx.chat.llm_loop import construct_message_history

        # Initialize sub-agent LLM
        sub_agent_llm = get_llm_for_persona(
            persona=self.target_persona,
            user=self.user,
            llm_override=None,
        )

        token_counter = get_llm_token_counter(sub_agent_llm)

        # Fresh message history with task
        initial_message = ChatMessageSimple(
            message=task,
            token_count=token_counter(task),
            message_type=MessageType.USER,
        )
        msg_history: list[ChatMessageSimple] = [initial_message]

        # Citation processor (KEEP_MARKERS mode)
        citation_processor = DynamicCitationProcessor(
            citation_mode=CitationMode.KEEP_MARKERS
        )

        # Construct tools for sub-agent
        tools = construct_tools(
            persona=self.target_persona,
            db_session=self.db_session,
            emitter=self.emitter,
            user=self.user,
            llm=sub_agent_llm,
            search_tool_config=None,
            custom_tool_config=None,
            allowed_tool_ids=None,
            search_usage_forcing_setting=SearchToolUsage.AUTO,
        )

        # Flatten tools and filter out agent tools to prevent deep nesting
        all_tools = [tool for tool_list in tools.values() for tool in tool_list]
        current_tools = [t for t in all_tools if not isinstance(t, AgentTool)]

        # Build system prompt
        system_prompt_str = build_system_prompt(
            base_system_prompt=self.target_persona.system_prompt or "",
            datetime_aware=self.target_persona.datetime_aware,
            tools=current_tools,
            should_cite_documents=True,
        )

        system_prompt = ChatMessageSimple(
            message=system_prompt_str,
            token_count=token_counter(system_prompt_str),
            message_type=MessageType.SYSTEM,
        )

        # Run LLM cycles
        final_answer = ""
        next_citation_num = starting_citation_num
        for cycle in range(AGENT_CYCLE_CAP + 1):
            out_of_cycles = cycle == AGENT_CYCLE_CAP
            cycle_tools = [] if out_of_cycles else current_tools

            # Build reminder
            reminder_text = build_reminder_message(
                reminder_text=self.target_persona.task_prompt,
                include_citation_reminder=True,
                is_last_cycle=out_of_cycles,
            ) or ""
            reminder_msg = ChatMessageSimple(
                message=reminder_text,
                token_count=token_counter(reminder_text),
                message_type=MessageType.USER,
            )

            # Construct full history
            full_history = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=msg_history,
                reminder_message=reminder_msg,
                project_files=None,
                available_tokens=sub_agent_llm.config.max_input_tokens,
            )

            # Call LLM
            tool_defs = [t.tool_definition() for t in cycle_tools]
            tool_choice = (
                ToolChoiceOptions.AUTO if cycle_tools else ToolChoiceOptions.NONE
            )

            llm_result, _ = run_llm_step(
                emitter=self.emitter,
                history=full_history,
                tool_definitions=tool_defs,
                tool_choice=tool_choice,
                llm=sub_agent_llm,
                placement=Placement(
                    turn_index=placement.turn_index,
                    tab_index=placement.tab_index,
                    sub_turn_index=cycle,
                ),
                citation_processor=citation_processor,
                state_container=None,
            )

            if llm_result.answer:
                final_answer = llm_result.answer
                if not llm_result.tool_calls:
                    break

            # Execute tool calls
            if llm_result.tool_calls:
                tool_call_results = run_tool_calls(
                    tool_calls=llm_result.tool_calls,
                    tools=cycle_tools,
                    message_history=full_history,
                    memories=None,
                    user_info=None,
                    citation_mapping={},
                    next_citation_num=next_citation_num,
                    max_concurrent_tools=3,
                    # Pass the current agent_call_stack to prevent infinite loops
                    agent_call_stack=agent_call_stack,
                )

                # Add to history
                for tool_result in tool_call_results.tool_responses:
                    tool_call = tool_result.tool_call
                    if tool_call is None:
                        raise ValueError("Tool response missing tool_call reference")
                    update_citation_processor_from_tool_response(
                        tool_result, citation_processor
                    )
                    msg_history.append(ChatMessageSimple(
                        message=tool_call.to_msg_str(),
                        message_type=MessageType.TOOL_CALL,
                        tool_call_id=tool_call.tool_call_id,
                        token_count=token_counter(tool_call.to_msg_str()),
                    ))
                    msg_history.append(ChatMessageSimple(
                        message=tool_result.llm_facing_response,
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=tool_call.tool_call_id,
                        token_count=token_counter(tool_result.llm_facing_response),
                    ))
                next_citation_num = citation_processor.get_next_citation_number()

        return AgentCallResult(
            answer=final_answer,
            citation_mapping=citation_processor.get_seen_citations(),
            token_count=token_counter(final_answer),
        )
