from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import SessionTransaction

from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import StreamingError
from onyx.chat.process_message import AnswerStream
from onyx.chat.process_message import remove_answer_citations
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.users import get_user_by_email
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.evals.models import EvalToolResult
from onyx.evals.models import ToolAssertion
from onyx.evals.provider import get_default_provider
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PythonToolStart
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


@contextmanager
def isolated_ephemeral_session_factory(
    engine: Engine,
) -> Generator[Callable[[], Session], None, None]:
    """
    Create a session factory that creates sessions that run in a transaction that gets rolled back.
    This is useful for running evals without any lasting db side effects.
    """
    tenant_id = get_current_tenant_id()
    schema_translate_map = {None: tenant_id}
    conn = engine.connect().execution_options(schema_translate_map=schema_translate_map)
    outer_tx = conn.begin()
    Maker = sessionmaker(bind=conn, expire_on_commit=False, future=True)

    def make_session() -> Session:
        s = Maker()
        s.begin_nested()

        @event.listens_for(s, "after_transaction_end")
        def _restart_savepoint(
            session: Session, transaction: SessionTransaction
        ) -> None:
            if transaction.nested and not (
                transaction._parent is not None and transaction._parent.nested
            ):
                session.begin_nested()

        return s

    try:
        yield make_session
    finally:
        outer_tx.rollback()
        conn.close()


class GatherStreamResult(BaseModel):
    """Result of gathering a stream with tool call information."""

    answer: str
    answer_citationless: str
    tools_called: list[str]
    tool_call_details: list[dict[str, Any]]
    message_id: int
    error_msg: str | None = None
    citations: list[CitationInfo] = []


def gather_stream_with_tools(packets: AnswerStream) -> GatherStreamResult:
    """
    Gather streaming packets and extract both answer content and tool call information.

    Returns a GatherStreamResult containing the answer and all tools that were called.
    """
    answer: str | None = None
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    tools_called: list[str] = []
    tool_call_details: list[dict[str, Any]] = []

    for packet in packets:
        if isinstance(packet, Packet):
            obj = packet.obj

            # Handle answer content
            if isinstance(obj, AgentResponseStart):
                pass  # AgentResponseStart contains metadata
            elif isinstance(obj, AgentResponseDelta):
                if answer is None:
                    answer = ""
                if obj.content:
                    answer += obj.content
            elif isinstance(obj, CitationInfo):
                citations.append(obj)

            # Track tool calls
            elif isinstance(obj, SearchToolStart):
                tool_name = "WebSearchTool" if obj.is_internet_search else "SearchTool"
                tools_called.append(tool_name)
                tool_call_details.append(
                    {
                        "tool_name": tool_name,
                        "tool_type": "search",
                        "is_internet_search": obj.is_internet_search,
                    }
                )
            elif isinstance(obj, ImageGenerationToolStart):
                tools_called.append("ImageGenerationTool")
                tool_call_details.append(
                    {
                        "tool_name": "ImageGenerationTool",
                        "tool_type": "image_generation",
                    }
                )
            elif isinstance(obj, PythonToolStart):
                tools_called.append("PythonTool")
                tool_call_details.append(
                    {
                        "tool_name": "PythonTool",
                        "tool_type": "python",
                        "code": obj.code,
                    }
                )
            elif isinstance(obj, OpenUrlStart):
                tools_called.append("OpenURLTool")
                tool_call_details.append(
                    {
                        "tool_name": "OpenURLTool",
                        "tool_type": "open_url",
                    }
                )
            elif isinstance(obj, CustomToolStart):
                tools_called.append(obj.tool_name)
                tool_call_details.append(
                    {
                        "tool_name": obj.tool_name,
                        "tool_type": "custom",
                    }
                )

        elif isinstance(packet, StreamingError):
            logger.warning(f"Streaming error during eval: {packet.error}")
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id

    if message_id is None:
        raise ValueError("Message ID is required")

    if answer is None:
        raise RuntimeError("Answer was not generated")

    return GatherStreamResult(
        answer=answer,
        answer_citationless=remove_answer_citations(answer),
        tools_called=tools_called,
        tool_call_details=tool_call_details,
        message_id=message_id,
        error_msg=error_msg,
        citations=citations,
    )


def evaluate_tool_assertions(
    tools_called: list[str],
    assertions: ToolAssertion | None,
) -> tuple[bool | None, str | None]:
    """
    Evaluate tool assertions against the tools that were called.

    Args:
        tools_called: List of tool names that were called during evaluation
        assertions: Tool assertions to check, or None if no assertions

    Returns:
        Tuple of (passed, details) where:
        - passed: True if assertions passed, False if failed, None if no assertions
        - details: Human-readable explanation of the result
    """
    if assertions is None:
        return None, None

    expected_tools = set(assertions.expected_tools)
    called_tools = set(tools_called)

    if assertions.require_all:
        # All expected tools must be called
        missing_tools = expected_tools - called_tools
        if missing_tools:
            return False, (
                f"Missing expected tools: {sorted(missing_tools)}. "
                f"Called tools: {sorted(called_tools)}"
            )
        return True, (
            f"All expected tools called: {sorted(expected_tools)}. "
            f"Called tools: {sorted(called_tools)}"
        )
    else:
        # At least one expected tool must be called
        matched_tools = expected_tools & called_tools
        if not matched_tools:
            return False, (
                f"None of expected tools called. "
                f"Expected one of: {sorted(expected_tools)}. "
                f"Called tools: {sorted(called_tools)}"
            )
        return True, (
            f"Expected tool(s) called: {sorted(matched_tools)}. "
            f"Called tools: {sorted(called_tools)}"
        )


def _get_answer_with_tools(
    eval_input: dict[str, Any],
    configuration: EvalConfigurationOptions,
) -> EvalToolResult:
    """
    Get answer from the chat system with full tool call tracking.

    Args:
        eval_input: Dictionary containing:
            - 'message': The user message to send
            - 'force_tools' (optional): List of tool types to force for this input
            - 'expected_tools' (optional): List of tool types expected to be called
            - 'require_all_tools' (optional): If true, all expected tools must be called
        configuration: Evaluation configuration options

    Returns:
        EvalToolResult containing the answer and tool call information
    """
    engine = get_sqlalchemy_engine()
    with isolated_ephemeral_session_factory(engine) as SessionLocal:
        with SessionLocal() as db_session:
            full_configuration = configuration.get_configuration(db_session)

            # Handle per-input tool forcing (from data file)
            forced_tool_ids: list[int] = []
            input_force_tools = eval_input.get("force_tools", [])
            if input_force_tools:
                from onyx.db.tools import get_builtin_tool
                from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

                for tool_type in input_force_tools:
                    if tool_type in BUILT_IN_TOOL_MAP:
                        tool_id = get_builtin_tool(
                            db_session, BUILT_IN_TOOL_MAP[tool_type]
                        ).id
                        if tool_id not in forced_tool_ids:
                            forced_tool_ids.append(tool_id)

            # Build tool assertions from per-input config
            tool_assertions: ToolAssertion | None = None
            input_expected_tools = eval_input.get("expected_tools", [])
            if input_expected_tools:
                tool_assertions = ToolAssertion(
                    expected_tools=input_expected_tools,
                    require_all=eval_input.get("require_all_tools", False),
                )

            user = (
                get_user_by_email(configuration.search_permissions_email, db_session)
                if configuration.search_permissions_email
                else None
            )

            request = prepare_chat_message_request(
                message_text=eval_input["message"],
                user=user,
                persona_id=None,
                persona_override_config=full_configuration.persona_override_config,
                message_ts_to_respond_to=None,
                retrieval_details=RetrievalDetails(),
                rerank_settings=None,
                db_session=db_session,
                skip_gen_ai_answer_generation=False,
                llm_override=full_configuration.llm,
                allowed_tool_ids=full_configuration.allowed_tool_ids,
                forced_tool_ids=forced_tool_ids if forced_tool_ids else None,
            )

            packets = stream_chat_message_objects(
                new_msg_req=request,
                user=user,
                db_session=db_session,
            )

            # Gather stream with tool call tracking
            result = gather_stream_with_tools(packets)

            # Evaluate tool assertions
            assertion_passed, assertion_details = evaluate_tool_assertions(
                result.tools_called, tool_assertions
            )

            logger.info(
                f"Eval completed. Tools called: {result.tools_called}.\n"
                f"Assertion passed: {assertion_passed}. Details: {assertion_details}\n"
            )

            return EvalToolResult(
                answer=result.answer,
                tools_called=result.tools_called,
                tool_call_details=result.tool_call_details,
                citations=result.citations,
                assertion_passed=assertion_passed,
                assertion_details=assertion_details,
            )


def run_eval(
    configuration: EvalConfigurationOptions,
    data: list[dict[str, Any]] | None = None,
    remote_dataset_name: str | None = None,
    provider: EvalProvider = get_default_provider(),
) -> EvalationAck:
    if data is not None and remote_dataset_name is not None:
        raise ValueError("Cannot specify both data and remote_dataset_name")

    if data is None and remote_dataset_name is None:
        raise ValueError("Must specify either data or remote_dataset_name")

    return provider.eval(
        task=lambda eval_input: _get_answer_with_tools(eval_input, configuration),
        configuration=configuration,
        data=data,
        remote_dataset_name=remote_dataset_name,
    )
