"""Chat admission and asynchronous replay, independent of the executing worker."""

import asyncio
import time
from collections.abc import Iterator
from typing import cast

from anyio import to_thread
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter

from onyx.chat.chat_state import ChatStateContainer, ChatTurnSetup
from onyx.chat.models import AnswerStreamPart, ChatFullResponse
from onyx.chat.pi.dispatch import enqueue, prepare_dispatch
from onyx.chat.pi.host_state import ChatHostSnapshot
from onyx.chat.pi.storage import StreamHub, load_state, state_redis, stream_key
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.query_and_chat.models import SendMessageRequest

PACKET = TypeAdapter(AnswerStreamPart)


def build_request(
    request: SendMessageRequest,
    user: User,
    llm_headers: dict[str, str],
    tool_headers: dict[str, str] | None,
) -> tuple[ChatTurnSetup, list[AnswerStreamPart]]:
    from onyx.chat.process_message import build_chat_turn
    from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
    from onyx.db.document_set import filter_document_set_names_by_user_access
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    if request.mock_llm_response is not None and not INTEGRATION_TESTS_MODE:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Mock responses require integration test mode"
        )
    with get_session_with_current_tenant() as session:
        filters = request.internal_search_filters
        if not user.is_anonymous and filters and filters.document_set:
            allowed = filter_document_set_names_by_user_access(
                db_session=session, document_set_names=filters.document_set, user=user
            )
            if set(filters.document_set) - set(allowed):
                raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
        overrides = (
            request.llm_overrides
            if request.llm_overrides and len(request.llm_overrides) > 1
            else None
        )
        generator = build_chat_turn(
            request,
            user,
            session,
            overrides,
            litellm_additional_headers=llm_headers,
            custom_tool_additional_headers=tool_headers,
            mcp_headers=request.mcp_headers,
            additional_context=request.additional_context,
        )
        packets = []
        while True:
            try:
                packets.append(next(generator))
            except StopIteration as result:
                setup = result.value
                break
        session.expunge_all()
        return setup, packets


async def chat_response(
    request: Request,
    message: SendMessageRequest,
    user: User,
    llm_headers: dict[str, str],
    tool_headers: dict[str, str] | None,
) -> StreamingResponse | ChatFullResponse:
    from onyx.chat.process_message import gather_stream_full

    setup, packets = await to_thread.run_sync(
        build_request, message, user, llm_headers, tool_headers
    )
    run_ids = await to_thread.run_sync(prepare_dispatch, setup, user.id, packets)
    # If Redis delivery fails, committed queued rows remain recoverable.
    for run_id in run_ids:
        try:
            await enqueue(run_id)
        except Exception:
            from onyx.utils.logger import setup_logger

            setup_logger().exception("Agent dispatch deferred to reconciliation")
    hub: StreamHub = request.app.state.agent_stream_hub
    stream = hub.stream(stream_key(setup.chat_session_id, setup.processing_run_id))
    if message.stream:
        return StreamingResponse(stream, media_type="text/event-stream")
    collected: list[AnswerStreamPart] = []
    async for block in stream:
        collected.extend(
            PACKET.validate_json(line) for line in block.splitlines() if line
        )
    state = ChatStateContainer()
    try:
        snapshot = await to_thread.run_sync(
            load_state, run_ids[0], "result", ChatHostSnapshot
        )
        snapshot.state.restore(state)
    except ValueError:
        pass
    result = gather_stream_full(iter(collected), state)
    if result.chat_session_id is None:
        result.chat_session_id = setup.chat_session_id
    return result


def queued_sync(
    setup: ChatTurnSetup,
    user: User,
    packets: list[AnswerStreamPart],
    external_state: ChatStateContainer | None,
) -> Iterator[AnswerStreamPart]:
    """Compatibility for synchronous bots and evaluations; the web API uses async replay."""
    run_ids = prepare_dispatch(setup, user.id, packets)

    async def submit() -> None:
        for run_id in run_ids:
            await enqueue(run_id)

    asyncio.run(submit())
    redis = state_redis()
    key = stream_key(setup.chat_session_id, setup.processing_run_id)
    cursor = len(packets)
    while True:
        blocks = cast(list[bytes], redis.lrange(key, cursor, cursor + 127))
        if blocks:
            cursor += len(blocks)
            for block in blocks:
                yield PACKET.validate_json(block)
        elif redis.exists(key + ":done"):
            break
        elif redis.exists(key + ":gap") or not redis.exists(key + ":bytes"):
            raise RuntimeError("Agent stream expired")
        else:
            time.sleep(0.2)
    if external_state:
        load_state(run_ids[0], "result", ChatHostSnapshot).state.restore(external_state)
