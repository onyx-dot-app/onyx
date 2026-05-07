import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from typing import ClassVar
from typing import Generic
from typing import TypeVar

from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.fake_tools.agent_loop_utils import append_think_tool_messages
from onyx.tools.fake_tools.agent_loop_utils import emit_agent_failure
from onyx.tools.fake_tools.agent_loop_utils import find_special_tool_calls
from onyx.tools.fake_tools.agent_loop_utils import should_force_finalize
from onyx.tools.models import ToolCallKickoff
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

logger = setup_logger()

ResultT = TypeVar("ResultT")


class AgenticAgentBase(ABC, Generic[ResultT]):
    """Abstract base for agentic-loop tools."""

    agent_name: ClassVar[str]
    max_cycles: ClassVar[int]
    force_finalize_seconds: ClassVar[float]
    finalize_tool_name: ClassVar[str]
    max_step_tokens: ClassVar[int]
    is_deep_research: ClassVar[bool] = False

    def __init__(
        self,
        kickoff: ToolCallKickoff,
        emitter: Emitter,
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None = None,
    ):
        self.kickoff = kickoff
        self.emitter = emitter
        self.llm = llm
        self.token_counter = token_counter
        self.user_identity = user_identity
        self.is_reasoning_model = model_is_reasoning_model(
            llm.config.model_name, llm.config.model_provider
        )
        self.turn_index = kickoff.placement.turn_index
        self.tab_index = kickoff.placement.tab_index
        self.msg_history: list[ChatMessageSimple] = []
        self.most_recent_reasoning: str | None = None

    @abstractmethod
    def initial_user_message(self) -> ChatMessageSimple:
        """Build the first USER message, seeded into ``msg_history``."""

    @abstractmethod
    def render_system_prompt(self, cycle: int) -> str:
        """Render the system prompt for this cycle."""

    @abstractmethod
    def tool_definitions(self) -> list[dict[str, Any]]:
        """Tool definitions passed to the LLM step."""

    @abstractmethod
    def execute_tool_calls(
        self,
        tool_calls: list[ToolCallKickoff],
        step_result: LlmStepResult,
        step_placement: Placement,
    ) -> bool:
        """Dispatch non-special tool calls; returns False to break the loop."""

    @abstractmethod
    def finalize(self) -> ResultT:
        """Generate the user-facing answer and emit closing packets."""

    @contextmanager
    def setup(self) -> Iterator[None]:
        """Pre-loop setup / post-loop teardown. Default: no-op."""
        yield

    def emit_start(self) -> None:
        """Emit a start packet before the loop begins. Default: no-op."""
        return None

    def transform_step_packet(
        self, packet: Packet, step_placement: Placement  # noqa: ARG002
    ) -> Packet | None:
        """Transform a step packet before emit; return None to drop."""
        return packet

    def reminder_message(self) -> ChatMessageSimple | None:
        """Optional USER reminder message threaded into history each cycle."""
        return None

    def filter_tool_calls(
        self, tool_calls: list[ToolCallKickoff]
    ) -> list[ToolCallKickoff]:
        """Filter tool calls before special-tool detection."""
        return tool_calls

    def custom_token_processor(self) -> Callable[..., Any] | None:
        """Token processor passed to the LLM step."""
        return (
            create_think_tool_token_processor() if not self.is_reasoning_model else None
        )

    @property
    def root_placement(self) -> Placement:
        return Placement(turn_index=self.turn_index, tab_index=self.tab_index)

    def run(self) -> ResultT | None:
        with function_span(self.agent_name) as span:
            span.span_data.input = str(self.kickoff.tool_args)
            try:
                with self.setup():
                    self.emit_start()
                    self.msg_history = [self.initial_user_message()]

                    start_time = time.monotonic()
                    cycle = 0
                    llm_cycles = 0
                    reasoning_cycles = 0

                    while cycle < self.max_cycles:
                        if should_force_finalize(
                            start_time=start_time,
                            timeout_seconds=self.force_finalize_seconds,
                            agent_name=self.agent_name,
                        ):
                            break

                        step_placement = Placement(
                            turn_index=self.turn_index,
                            tab_index=self.tab_index,
                            sub_turn_index=llm_cycles + reasoning_cycles,
                        )
                        result, has_reasoned = self._run_llm_step(step_placement, cycle)
                        if has_reasoned:
                            reasoning_cycles += 1

                        tool_calls = self.filter_tool_calls(result.tool_calls or [])
                        if not tool_calls:
                            logger.warning(
                                "%s LLM produced no tool calls; forcing finalize",
                                self.agent_name,
                            )
                            break

                        special = find_special_tool_calls(
                            tool_calls=tool_calls,
                            finalize_tool_name=self.finalize_tool_name,
                        )
                        if special.finalize_tool_call:
                            break
                        if special.think_tool_call:
                            with function_span("think_tool") as think_span:
                                think_span.span_data.input = str(
                                    special.think_tool_call.tool_args
                                )
                                append_think_tool_messages(
                                    history=self.msg_history,
                                    think_tool_call=special.think_tool_call,
                                    token_counter=self.token_counter,
                                )
                                self.most_recent_reasoning = result.reasoning
                            cycle += 1
                            continue

                        if not self.execute_tool_calls(
                            tool_calls=tool_calls,
                            step_result=result,
                            step_placement=step_placement,
                        ):
                            break

                        self.most_recent_reasoning = None
                        cycle += 1
                        llm_cycles += 1

                    finalized = self.finalize()
                    span.span_data.output = str(finalized)
                    return finalized

            except Exception as e:
                emit_agent_failure(
                    emitter=self.emitter,
                    placement=self.root_placement,
                    agent_name=self.agent_name,
                    exc=e,
                )
                return None

    def _run_llm_step(
        self, step_placement: Placement, cycle: int
    ) -> tuple[LlmStepResult, bool]:
        """Run one LLM step and return ``(result, has_reasoned)``."""
        system_prompt_str = self.render_system_prompt(cycle)
        system_prompt = ChatMessageSimple(
            message=system_prompt_str,
            token_count=self.token_counter(system_prompt_str),
            message_type=MessageType.SYSTEM,
        )
        constructed_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=self.msg_history,
            reminder_message=self.reminder_message(),
            context_files=None,
            available_tokens=self.llm.config.max_input_tokens,
        )
        step_generator = run_llm_step_pkt_generator(
            history=constructed_history,
            tool_definitions=self.tool_definitions(),
            tool_choice=ToolChoiceOptions.REQUIRED,
            llm=self.llm,
            placement=step_placement,
            citation_processor=None,
            state_container=None,
            reasoning_effort=ReasoningEffort.LOW,
            final_documents=None,
            user_identity=self.user_identity,
            custom_token_processor=self.custom_token_processor(),
            use_existing_tab_index=True,
            is_deep_research=self.is_deep_research,
            max_tokens=self.max_step_tokens,
        )
        while True:
            try:
                packet = next(step_generator)
                transformed = self.transform_step_packet(packet, step_placement)
                if transformed is not None:
                    self.emitter.emit(transformed)
            except StopIteration as e:
                return e.value
