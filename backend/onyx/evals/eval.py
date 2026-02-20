import time
from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import SessionTransaction

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.models import ChatFullResponse
from onyx.chat.process_message import gather_stream_full
from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.chat import create_chat_session
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.users import get_user_by_email
from onyx.evals.models import ChatFullEvalResult
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalMessage
from onyx.evals.models import EvalProvider
from onyx.evals.models import EvalTimings
from onyx.evals.models import EvalToolResult
from onyx.evals.models import MultiTurnEvalResult
from onyx.evals.models import ToolAssertion
from onyx.evals.provider import get_provider
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import AUTO_PLACE_AFTER_LATEST_MESSAGE
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import SendMessageRequest
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


def _chat_full_response_to_eval_result(
    full: ChatFullResponse,
    stream_start_time: float,
) -> ChatFullEvalResult:
    """Map ChatFullResponse from gather_stream_full to eval result components."""
    tools_called = [tc.tool_name for tc in full.tool_calls]
    tool_call_details: list[dict[str, Any]] = [
        {"tool_name": tc.tool_name, "tool_arguments": tc.tool_arguments}
        for tc in full.tool_calls
    ]
    stream_end_time = time.time()
    total_ms = (stream_end_time - stream_start_time) * 1000
    timings = EvalTimings(
        total_ms=total_ms,
        llm_first_token_ms=None,
        tool_execution_ms={},
        stream_processing_ms=total_ms,
    )
    return ChatFullEvalResult(
        answer=full.answer,
        tools_called=tools_called,
        tool_call_details=tool_call_details,
        citations=full.citation_info,
        timings=timings,
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
            - 'model' (optional): Model version to use (e.g., "gpt-4o", "claude-3-5-sonnet")
            - 'model_provider' (optional): Model provider (e.g., "openai", "anthropic")
            - 'temperature' (optional): Temperature for the model
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

            # Handle per-input model configuration
            llm_override = full_configuration.llm
            input_model = eval_input.get("model")
            input_model_provider = eval_input.get("model_provider")
            input_temperature = eval_input.get("temperature")

            if input_model or input_model_provider or input_temperature is not None:
                # Create a new LLMOverride with per-input values, falling back to config
                llm_override = LLMOverride(
                    model_provider=input_model_provider or llm_override.model_provider,
                    model_version=input_model or llm_override.model_version,
                    temperature=(
                        input_temperature
                        if input_temperature is not None
                        else llm_override.temperature
                    ),
                )

            user = get_user_by_email(configuration.search_permissions_email, db_session)
            if not user:
                raise ValueError(
                    f"User not found for email: {configuration.search_permissions_email}"
                )

            forced_tool_id = forced_tool_ids[0] if forced_tool_ids else None
            request = SendMessageRequest(
                message=eval_input["message"],
                llm_override=llm_override,
                allowed_tool_ids=full_configuration.allowed_tool_ids,
                forced_tool_id=forced_tool_id,
                chat_session_info=ChatSessionCreationRequest(
                    persona_id=DEFAULT_PERSONA_ID,
                    description="Eval session",
                ),
            )

            stream_start_time = time.time()
            state_container = ChatStateContainer()
            packets = handle_stream_message_objects(
                new_msg_req=request,
                user=user,
                db_session=db_session,
                external_state_container=state_container,
            )
            full = gather_stream_full(packets, state_container)

            result = _chat_full_response_to_eval_result(full, stream_start_time)

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
                timings=result.timings,
            )


def _get_multi_turn_answer_with_tools(
    eval_input: dict[str, Any],
    configuration: EvalConfigurationOptions,
) -> MultiTurnEvalResult:
    """
    Get answers from a multi-turn conversation with tool call tracking for each turn.

    Args:
        eval_input: Dictionary containing:
            - 'messages': List of message dicts, each with:
                - 'message': The user message text
                - 'expected_tools' (optional): List of expected tool types
                - 'require_all_tools' (optional): If true, all expected tools must be called
                - 'model' (optional): Model version override for this turn
                - 'model_provider' (optional): Provider override for this turn
                - 'temperature' (optional): Temperature override for this turn
                - 'force_tools' (optional): List of tool types to force
        configuration: Evaluation configuration options

    Returns:
        MultiTurnEvalResult containing per-turn results and aggregate metrics
    """
    messages_data = eval_input.get("messages", [])
    if not messages_data:
        raise ValueError("Multi-turn eval requires 'messages' array in input")

    # Parse messages into EvalMessage objects
    messages: list[EvalMessage] = []
    for msg_data in messages_data:
        messages.append(
            EvalMessage(
                message=msg_data["message"],
                expected_tools=msg_data.get("expected_tools", []),
                require_all_tools=msg_data.get("require_all_tools", False),
                model=msg_data.get("model"),
                model_provider=msg_data.get("model_provider"),
                temperature=msg_data.get("temperature"),
                force_tools=msg_data.get("force_tools", []),
            )
        )

    turn_results: list[EvalToolResult] = []

    engine = get_sqlalchemy_engine()
    with isolated_ephemeral_session_factory(engine) as SessionLocal:
        with SessionLocal() as db_session:
            full_configuration = configuration.get_configuration(db_session)

            user = get_user_by_email(configuration.search_permissions_email, db_session)
            if not user:
                raise ValueError(
                    f"User not found for email: {configuration.search_permissions_email}"
                )
            # Cache user_id to avoid SQLAlchemy expiration issues
            user_id = user.id

            # Create a single chat session for all turns
            chat_session = create_chat_session(
                db_session=db_session,
                description="Multi-turn eval session",
                user_id=user_id,
                persona_id=DEFAULT_PERSONA_ID,
                onyxbot_flow=True,
            )
            chat_session_id = chat_session.id

            # Process each turn sequentially
            for turn_idx, msg in enumerate(messages):
                logger.info(
                    f"Processing turn {turn_idx + 1}/{len(messages)}: {msg.message[:50]}..."
                )

                # Handle per-turn tool forcing
                forced_tool_ids: list[int] = []
                if msg.force_tools:
                    from onyx.db.tools import get_builtin_tool
                    from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

                    for tool_type in msg.force_tools:
                        if tool_type in BUILT_IN_TOOL_MAP:
                            tool_id = get_builtin_tool(
                                db_session, BUILT_IN_TOOL_MAP[tool_type]
                            ).id
                            if tool_id not in forced_tool_ids:
                                forced_tool_ids.append(tool_id)

                # Build tool assertions for this turn
                tool_assertions: ToolAssertion | None = None
                if msg.expected_tools:
                    tool_assertions = ToolAssertion(
                        expected_tools=msg.expected_tools,
                        require_all=msg.require_all_tools,
                    )

                # Handle per-turn model configuration
                llm_override = full_configuration.llm
                if msg.model or msg.model_provider or msg.temperature is not None:
                    llm_override = LLMOverride(
                        model_provider=msg.model_provider
                        or llm_override.model_provider,
                        model_version=msg.model or llm_override.model_version,
                        temperature=(
                            msg.temperature
                            if msg.temperature is not None
                            else llm_override.temperature
                        ),
                    )

                # Create request for this turn using SendMessageRequest (same API as handle_stream_message_objects)
                # Use AUTO_PLACE_AFTER_LATEST_MESSAGE to chain messages
                forced_tool_id = forced_tool_ids[0] if forced_tool_ids else None
                request = SendMessageRequest(
                    chat_session_id=chat_session_id,
                    parent_message_id=AUTO_PLACE_AFTER_LATEST_MESSAGE,
                    message=msg.message,
                    llm_override=llm_override,
                    allowed_tool_ids=full_configuration.allowed_tool_ids,
                    forced_tool_id=forced_tool_id,
                )

                # Stream and gather results for this turn via handle_stream_message_objects + gather_stream_full
                stream_start_time = time.time()
                state_container = ChatStateContainer()
                packets = handle_stream_message_objects(
                    new_msg_req=request,
                    user=user,
                    db_session=db_session,
                    external_state_container=state_container,
                )
                full = gather_stream_full(packets, state_container)

                result = _chat_full_response_to_eval_result(full, stream_start_time)

                # Evaluate tool assertions for this turn
                assertion_passed, assertion_details = evaluate_tool_assertions(
                    result.tools_called, tool_assertions
                )

                logger.info(
                    f"Turn {turn_idx + 1} completed. Tools called: {result.tools_called}.\n"
                    f"Assertion passed: {assertion_passed}. Details: {assertion_details}\n"
                )

                turn_results.append(
                    EvalToolResult(
                        answer=result.answer,
                        tools_called=result.tools_called,
                        tool_call_details=result.tool_call_details,
                        citations=result.citations,
                        assertion_passed=assertion_passed,
                        assertion_details=assertion_details,
                        timings=result.timings,
                    )
                )

    # Calculate aggregate metrics
    pass_count = sum(1 for r in turn_results if r.assertion_passed is True)
    fail_count = sum(1 for r in turn_results if r.assertion_passed is False)
    # Consider "all passed" only if there are no failures
    # (turns with no assertions don't count as failures)
    all_passed = fail_count == 0

    return MultiTurnEvalResult(
        turn_results=turn_results,
        all_passed=all_passed,
        pass_count=pass_count,
        fail_count=fail_count,
        total_turns=len(turn_results),
    )


def run_eval(
    configuration: EvalConfigurationOptions,
    data: list[dict[str, Any]] | None = None,
    remote_dataset_name: str | None = None,
    provider: EvalProvider = get_provider(),
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
        multi_turn_task=lambda eval_input: _get_multi_turn_answer_with_tools(
            eval_input, configuration
        ),
    )
