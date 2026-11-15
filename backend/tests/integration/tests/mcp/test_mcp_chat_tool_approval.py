"""MCP tool calls in chat follow the action policies and wait for the user:
the turn stops, and the response continues in a new stream after the
decisions. The wait lives in storage, so any API server can continue it; the
external dependency tests resume one in another process."""

import json
import threading
import time
from collections.abc import Callable, Generator, Iterator
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.agents.models import RunStatus
from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.cache.factory import get_cache_backend
from onyx.chat.models import ChatFullResponse
from onyx.chat.process_message import run_chat_turn
from onyx.chat.run_store import RESUME_FAILED_MESSAGE, ownerless_response_ids
from onyx.configs.constants import DISCORD_SERVICE_API_KEY_NAME
from onyx.db.api_key import insert_api_key, remove_api_key
from onyx.db.chat import delete_chat_session
from onyx.db.discord_bot import (
    delete_discord_service_api_key,
    get_discord_service_api_key,
    get_or_create_discord_service_api_key,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ActionPolicy, ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import (
    ApprovalRequest,
    ChatMessage,
    ChatResponseCheckpoint,
    ChatSession,
    User,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.server.api_key.models import APIKeyArgs
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    CurrentStreamInfo,
    MessageOrigin,
    SendMessageRequest,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AWAITING_APPROVAL,
    OverallStop,
    Packet,
    PacketObj,
    ToolApprovalOutcome,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.tool_implementations.code_mode.stubs import function_name
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import (
    DATestChatSession,
    DATestPersona,
    DATestUser,
)
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)
from tests.integration.tests.mcp.conftest import ConnectedMCPServer

CALL_ID = "call_hello"
OnRequest = Callable[[Packet, ToolApprovalRequest], None]
# Makes the admin's chat whose agent has the server's `hello` tool, or the
# given tools.
NewChat = Callable[..., UUID]


def _hello(server: ConnectedMCPServer, call_id: str, name: str) -> ToolCall:
    return ToolCall(
        id=call_id, name=server.callable_name("hello"), arguments={"name": name}
    )


@pytest.fixture
def new_chat(
    connected_mcp_server: ConnectedMCPServer, admin_user: DATestUser
) -> Generator[NewChat, None, None]:
    """Teardown deletes the chats and their agents."""
    chats: list[tuple[DATestChatSession, DATestPersona]] = []

    def create(tools: list[str] | None = None) -> UUID:
        persona = PersonaManager.create(
            tool_ids=[
                connected_mcp_server.tool_ids[name] for name in tools or ["hello"]
            ],
            user_performing_action=admin_user,
        )
        chat = ChatSessionManager.create(
            persona_id=persona.id, user_performing_action=admin_user
        )
        chats.append((chat, persona))
        return chat.id

    try:
        yield create
    finally:
        for chat, persona in chats:
            ChatSessionManager.delete(chat, admin_user)
            PersonaManager.delete(persona, admin_user)


def _request(chat_session_id: UUID, message: str = "Say hello.") -> SendMessageRequest:
    return SendMessageRequest(
        chat_session_id=chat_session_id, message=message, parent_message_id=None
    )


def _set_policies(
    server: ConnectedMCPServer, admin_user: DATestUser, **settings: object
) -> None:
    client.patch(
        f"{API_SERVER_URL}/admin/mcp/server/{server.id}",
        json=settings,
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    ).raise_for_status()


def _decide(user: DATestUser, approval_id: str, decision: str) -> httpx.Response:
    return client.post(
        f"{API_SERVER_URL}/chat/approvals/{approval_id}/decision",
        json={"decision": decision},
        headers=user.headers,
        cookies=user.cookies,
    )


def _status(user: DATestUser, chat_session_id: UUID) -> dict[str, object]:
    status = client.get(
        f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}/status",
        headers=user.headers,
        cookies=user.cookies,
    )
    status.raise_for_status()
    return status.json()


def _saved_answer(
    chat_session_id: UUID,
    message_id: int,
    expected: str,
    *,
    headers: dict[str, str],
    cookies: dict[str, str] | None = None,
) -> str | None:
    """The saved answer of a response that continued after the request
    returned, once it is `expected` or 30 seconds pass."""
    deadline = time.monotonic() + 30
    while True:
        detail = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
            headers=headers,
            cookies=cookies,
        )
        detail.raise_for_status()
        answer = next(
            (
                message["message"]
                for message in detail.json()["messages"]
                if message["message_id"] == message_id
            ),
            None,
        )
        if answer == expected or time.monotonic() > deadline:
            return answer
        time.sleep(0.5)


def _packets(response: httpx.Response) -> Iterator[Packet]:
    response.raise_for_status()
    for line in response.iter_lines():
        data = json.loads(line) if line else {}
        if "obj" in data:
            yield Packet.model_validate(data)


def _waiting(packets: list[Packet]) -> list[tuple[Packet, ToolApprovalRequest]]:
    """The requests that a stream asked and did not resolve."""
    resolved = {
        packet.obj.approval_id
        for packet in packets
        if isinstance(packet.obj, ToolApprovalResolved)
    }
    return [
        (packet, packet.obj)
        for packet in packets
        if isinstance(packet.obj, ToolApprovalRequest)
        and packet.obj.approval_id not in resolved
    ]


def _stop_reason(packets: list[Packet]) -> str | None:
    stops = [packet.obj for packet in packets if isinstance(packet.obj, OverallStop)]
    return stops[-1].stop_reason if stops else None


def _converse(
    streaming_api: str,
    user: DATestUser,
    request: SendMessageRequest,
    on_request: OnRequest,
    on_continued: Callable[[], None] = lambda: None,
) -> list[list[Packet]]:
    """Send a message over a real HTTP stream, as a client does. A stream that
    stops to wait for approval calls `on_request` for each request it left
    waiting; then the client reads the chat's status and follows the
    continuation's new stream from cursor 0. Returns each stream's packets."""
    assert request.chat_session_id is not None
    streams: list[list[Packet]] = []
    with httpx.Client(
        base_url=streaming_api,
        headers=user.headers,
        cookies=user.cookies,
        timeout=60,
    ) as http:
        with http.stream(
            "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
        ) as response:
            streams.append(list(_packets(response)))
        ended_streams: set[int] = set()
        while _stop_reason(streams[-1]) == AWAITING_APPROVAL:
            for packet, waiting in _waiting(streams[-1]):
                on_request(packet, waiting)
            status = http.get(f"/chat/chat-session/{request.chat_session_id}/status")
            status.raise_for_status()
            current = status.json()["current_stream"]
            if current is None:
                break
            stream_id = current["stream_id"]
            # Each continuation streams under a new ID.
            assert stream_id not in ended_streams
            ended_streams.add(stream_id)
            with http.stream(
                "GET",
                f"/chat/chat-session/{request.chat_session_id}/resume-stream",
                params={"cursor": 0, "stream_id": stream_id},
            ) as continued:
                on_continued()
                streams.append(list(_packets(continued)))
    return streams


def _response_of(approval_id: str) -> int:
    with get_session_with_current_tenant() as db_session:
        return db_session.get_one(ApprovalRequest, UUID(approval_id)).chat_message_id


def _of_type[T](packets: list[Packet], kind: type[T]) -> list[T]:
    return [packet.obj for packet in packets if isinstance(packet.obj, kind)]


def _saved_approval_packets(
    user: DATestUser, chat_session_id: UUID
) -> list[tuple[Placement, PacketObj]]:
    """The approval packets of the chat's saved responses, as a reload gets
    them. Like the stream's, their placements have the response's model index."""
    detail = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    detail.raise_for_status()
    return [
        (packet.placement.model_copy(update={"model_index": 0}), packet.obj)
        for response in detail.json()["packets"]
        for packet in map(Packet.model_validate, response)
        if isinstance(packet.obj, (ToolApprovalRequest, ToolApprovalResolved))
    ]


@pytest.mark.parametrize(
    "decision, outcome",
    [("approve_once", "approved"), ("reject", "rejected")],
)
def test_a_waiting_turn_stops_and_its_response_continues_after_the_decision(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    basic_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    decision: str,
    outcome: ToolApprovalOutcome,
) -> None:
    """With the default ASK policy, the stream asks at the call's card and
    stops. The turn releases the chat and its server: the response waits in
    its checkpoint. The decision continues it in a new stream that replays the
    response, then runs or skips the tool. A decision is saved once."""
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        # The answer waits until the client follows the continuation.
        Reply(
            text="Done. All set.",
            conditions=RequestConditions(has_results_for=[CALL_ID]),
            pause_after_first_chunk="answer",
        ),
    )
    chat_session_id = new_chat()
    decisions: list[httpx.Response] = []
    continued_stream: dict[str, object] = {}
    waiting: list[tuple[bool, RunStatus | None, bool, bool]] = []

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        response_id = _response_of(request.approval_id)
        with get_session_with_current_tenant() as db_session:
            response = db_session.get_one(ChatMessage, response_id)
            saved = db_session.get(ChatResponseCheckpoint, response_id) is not None
            waiting.append(
                (
                    bool(_status(admin_user, chat_session_id)["is_processing"]),
                    response.response_status,
                    saved,
                    bool(ownerless_response_ids(get_cache_backend(), [response_id])),
                )
            )
        opposite = "approve_once" if decision == "reject" else "reject"
        decisions.append(_decide(admin_user, request.approval_id, decision))
        stream = CurrentStreamInfo.model_validate(
            _status(admin_user, chat_session_id)["current_stream"]
        )
        continued_stream.update(stream.model_dump())
        decisions.extend(
            [
                _decide(admin_user, request.approval_id, decision),
                _decide(admin_user, request.approval_id, opposite),
                _decide(basic_user, request.approval_id, decision),
            ]
        )

    try:
        first, continued = _converse(
            streaming_api,
            admin_user,
            _request(chat_session_id),
            on_request,
            on_continued=lambda: mock_llm.release_gate("answer"),
        )
    finally:
        mock_llm.release_gate("answer")

    [(request_packet, request)] = _waiting(first)
    assert request.model_dump(include={"tool_call_id", "tool_name", "arguments"}) == {
        "tool_call_id": CALL_ID,
        "tool_name": hello.name,
        "arguments": {"name": name},
    }
    assert request.display_name
    # Not processing, suspended with its checkpoint, and no server owns it.
    assert waiting == [(False, RunStatus.SUSPENDED, True, True)]
    assert first[-1].obj == OverallStop(stop_reason=AWAITING_APPROVAL)

    # The continuation replays the card, then shows the decision and result.
    card = [
        packet.obj.type
        for packet in continued
        if packet.placement == request_packet.placement
        and packet.obj.type
        in {
            "custom_tool_start",
            "tool_approval_request",
            "tool_approval_resolved",
            "custom_tool_delta",
        }
    ]
    assert card[:3] == [
        "custom_tool_start",
        "tool_approval_request",
        "tool_approval_resolved",
    ]
    assert ("custom_tool_delta" in card) is (outcome == "approved")
    assert _of_type(continued, ToolApprovalResolved) == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome=outcome)
    ]
    assert continued[-1].obj == OverallStop(stop_reason="finished")

    # The decision names the stream that continues its response, which the
    # status reported too; repeating it while that stream runs names it again.
    # The opposite decision conflicts; another user cannot see the request.
    saved = {
        "approval_id": request.approval_id,
        "decision": outcome.upper(),
        "decided_via": "USER",
        "continuation": {
            "stream_id": continued_stream["stream_id"],
            "response_ids": [_response_of(request.approval_id)],
        },
    }
    assert continued_stream["response_ids"] == [_response_of(request.approval_id)]
    assert continued_stream["stream_id"] != _response_of(request.approval_id)
    assert [(response.status_code, response.json()) for response in decisions[:2]] == [
        (200, saved),
        (200, saved),
    ]
    assert decisions[2].status_code == 409
    assert decisions[3].status_code == 404

    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None
    if outcome == "approved":
        assert f"Hello, {name}!" in tool_result
    else:
        assert (
            tool_result
            == f"The user rejected this {hello.name} call, so it did not run."
        )
    with get_session_with_current_tenant() as db_session:
        assert (
            db_session.get(ChatResponseCheckpoint, _response_of(request.approval_id))
            is None
        )

    # A reload shows the request's record where the stream showed it.
    assert _saved_approval_packets(admin_user, chat_session_id) == [
        (request_packet.placement, request),
        (
            request_packet.placement,
            ToolApprovalResolved(approval_id=request.approval_id, outcome=outcome),
        ),
    ]


def test_a_reload_while_the_turn_waits_shows_the_request_and_the_stop(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    chat_session_id = new_chat()
    reloaded: list[list[tuple[Placement, PacketObj]]] = []
    stops: list[list[str | None]] = []
    versions: list[object] = [_status(admin_user, chat_session_id)["approvals_version"]]

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        reloaded.append(_saved_approval_packets(admin_user, chat_session_id))
        detail = client.get(
            f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        detail.raise_for_status()
        # A load and the status name one version; the request changed it.
        versions.append(detail.json()["approvals_version"])
        versions.append(_status(admin_user, chat_session_id)["approvals_version"])
        stops.append(
            [
                Packet.model_validate(packet).obj.model_dump().get("stop_reason")
                for response in detail.json()["packets"]
                for packet in response
                if packet["obj"]["type"] == "stop"
            ]
        )
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()
        versions.append(_status(admin_user, chat_session_id)["approvals_version"])

    first, _continued = _converse(
        streaming_api, admin_user, _request(chat_session_id), on_request
    )

    [(request_packet, request)] = _waiting(first)
    assert reloaded == [[(request_packet.placement, request)]]
    assert stops == [[AWAITING_APPROVAL]]
    before, loaded, polled, decided = versions
    assert loaded == polled
    assert len({before, polled, decided}) == 3


def test_approving_a_tool_that_an_admin_disabled_meanwhile_reports_it_disabled(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    decisions: list[dict[str, str]] = []

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        _set_policies(
            connected_mcp_server,
            admin_user,
            action_policies={"hello": ActionPolicy.DENY.value},
        )
        decided = _decide(admin_user, request.approval_id, "approve_once")
        decided.raise_for_status()
        decisions.append(decided.json())

    streams = _converse(streaming_api, admin_user, _request(new_chat()), on_request)

    assert [
        (decision["decision"], decision["decided_via"]) for decision in decisions
    ] == [("REJECTED", "POLICY")]
    assert [
        resolved.outcome for resolved in _of_type(streams[-1], ToolApprovalResolved)
    ] == ["disabled"]
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert (
        tool_result == f"The {hello.name} tool is disabled, so this call did not run."
    )


def test_a_tool_removed_while_its_call_waits_is_no_longer_available(
    connected_mcp_server: ConnectedMCPServer,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """The response continues with the agent's current tools."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    persona = PersonaManager.create(
        tool_ids=[connected_mcp_server.tool_ids["hello"]],
        user_performing_action=admin_user,
    )
    chat = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        PersonaManager.edit(
            persona,
            user_performing_action=admin_user,
            tool_ids=[connected_mcp_server.tool_ids["get_ticket"]],
        )
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    try:
        streams = _converse(streaming_api, admin_user, _request(chat.id), on_request)
    finally:
        ChatSessionManager.delete(chat, admin_user)
        PersonaManager.delete(persona, admin_user)

    assert len(streams) == 2
    assert mock_llm.requests_in("chat")[-1].tool_result(CALL_ID) == (
        UNAVAILABLE_CALL_MESSAGE
    )


def test_a_disabled_tool_is_not_offered_to_the_model(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    _set_policies(
        connected_mcp_server,
        admin_user,
        action_policies={"hello": ActionPolicy.DENY.value},
    )
    hello = connected_mcp_server.callable_name("hello")
    get_ticket = connected_mcp_server.callable_name("get_ticket")
    mock_llm.conversation(
        "chat",
        Reply(
            text="No greeting today.",
            conditions=RequestConditions(offers=[get_ticket], does_not_offer=[hello]),
        ),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=new_chat(["hello", "get_ticket"]),
        message="Say hello.",
        user_performing_action=admin_user,
    )

    assert response.error is None
    assert response.full_message == "No greeting today."
    [request] = mock_llm.requests_in("chat")
    assert get_ticket in request.tools and hello not in request.tools


@pytest.mark.parametrize("users_can_manage", [True, False])
def test_a_personal_always_policy_applies_only_where_users_can_manage(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    users_can_manage: bool,
) -> None:
    """Chat users set their own policy for an MCP server without Craft."""
    client.put(
        f"{API_SERVER_URL}/action-policies/mcp_server/{connected_mcp_server.id}",
        json={"action_policies": {"hello": ActionPolicy.ALWAYS.value}},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    ).raise_for_status()
    if not users_can_manage:
        _set_policies(connected_mcp_server, admin_user, users_can_manage_policies=False)
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    asked: list[str] = []

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        asked.append(request.approval_id)
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    _converse(streaming_api, admin_user, _request(new_chat()), on_request)

    assert len(asked) == (0 if users_can_manage else 1)
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


def test_approving_for_the_chat_continues_once_and_runs_later_calls(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """One decision of two requests does not continue the response; an
    approval for the chat decides both, and later calls do not ask."""
    first = _hello(connected_mcp_server, "call_a", "a")
    second = _hello(connected_mcp_server, "call_b", "b")
    later = _hello(connected_mcp_server, "call_c", "c")
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[first, second],
            conditions=RequestConditions(offers=[first.name]),
        ),
        Reply(
            text="Both done.",
            conditions=RequestConditions(has_results_for=["call_a", "call_b"]),
        ),
        Reply(tool_calls=[later], conditions=RequestConditions(offers=[later.name])),
        Reply(
            text="Done again.", conditions=RequestConditions(has_results_for=["call_c"])
        ),
    )
    chat_session_id = new_chat()
    asked: list[str] = []
    processing_after_first: list[bool] = []

    def grant(_packet: Packet, request: ToolApprovalRequest) -> None:
        asked.append(request.approval_id)
        if len(asked) == 2:
            _decide(admin_user, asked[1], "approve_once").raise_for_status()
            processing_after_first.append(
                bool(_status(admin_user, chat_session_id)["is_processing"])
            )
            _decide(admin_user, asked[0], "approve_session").raise_for_status()

    streams = _converse(streaming_api, admin_user, _request(chat_session_id), grant)

    assert len(streams) == 2
    assert processing_after_first == [False]
    assert sorted(
        (resolved.approval_id, resolved.outcome)
        for resolved in _of_type(streams[-1], ToolApprovalResolved)
    ) == sorted([(asked[0], "approved_for_chat"), (asked[1], "approved")])
    results = mock_llm.requests_in("chat")[-1]
    assert "Hello, a!" in (results.tool_result("call_a") or "")
    assert "Hello, b!" in (results.tool_result("call_b") or "")

    later_requests: list[str] = []

    def unexpected(_packet: Packet, request: ToolApprovalRequest) -> None:
        later_requests.append(request.approval_id)
        _decide(admin_user, request.approval_id, "reject").raise_for_status()

    later_streams = _converse(
        streaming_api,
        admin_user,
        _request(chat_session_id, "Say hello again.").model_copy(
            update={"parent_message_id": -1}
        ),
        unexpected,
    )

    assert later_requests == []
    assert len(later_streams) == 1
    later_result = mock_llm.requests_in("chat")[-1].tool_result("call_c")
    assert later_result is not None and "Hello, c!" in later_result


def test_a_waiting_chat_blocks_new_messages_and_its_wait_is_not_thought_time(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
        Reply(text="Second answer."),
    )
    chat_session_id = new_chat()
    blocked: list[httpx.Response] = []
    held_seconds = 3.0

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        # The stream ended with its stop, after the response parked; only a
        # parked selected response blocks sends.
        assert _parked(_response_of(request.approval_id))
        blocked.append(
            client.post(
                f"{API_SERVER_URL}/chat/send-chat-message",
                json=_request(chat_session_id, "Another question.").model_dump(
                    mode="json"
                )
                | {"parent_message_id": -1},
                headers=admin_user.headers,
                cookies=admin_user.cookies,
            )
        )
        time.sleep(held_seconds)
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    started = time.monotonic()
    _converse(streaming_api, admin_user, _request(chat_session_id), on_request)
    total_seconds = time.monotonic() - started

    [rejected] = blocked
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "APPROVAL_PENDING"
    # Once decided, the chat accepts messages again.
    accepted = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Another question.",
        user_performing_action=admin_user,
    )
    assert accepted.error is None and accepted.full_message == "Second answer."

    detail = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    detail.raise_for_status()
    [first_answer, _second] = [
        message
        for message in detail.json()["messages"]
        if message["message_type"] == "assistant"
    ]
    # The time it ran, without the wait for the decision.
    assert first_answer["processing_duration_seconds"] is not None
    assert first_answer["processing_duration_seconds"] < total_seconds - held_seconds


def test_a_response_that_cannot_continue_fails_once_and_frees_the_chat(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """A continuation that fails before its run starts ends the response as
    failed, with its saved state; nothing tries it again, and the chat
    accepts messages."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
    )
    mock_llm.conversation(
        "second",
        Reply(text="Second answer."),
        conditions=RequestConditions(prompt_contains=["Another question."]),
    )
    chat_session_id = new_chat()
    response_ids: list[int] = []

    def break_then_approve(_packet: Packet, request: ToolApprovalRequest) -> None:
        response_id = _response_of(request.approval_id)
        response_ids.append(response_id)
        with get_session_with_current_tenant() as db_session:
            checkpoint = db_session.get_one(ChatResponseCheckpoint, response_id)
            # The saved history no longer matches the checkpoint.
            checkpoint.state = {**checkpoint.state, "history_digest": "changed"}
            db_session.commit()
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    _converse(streaming_api, admin_user, _request(chat_session_id), break_then_approve)

    [response_id] = response_ids
    with get_session_with_current_tenant() as db_session:
        response = db_session.get_one(ChatMessage, response_id)
        assert response.response_status == RunStatus.ERROR
        assert (
            response.response_failure is not None
            and response.response_failure.message == RESUME_FAILED_MESSAGE
        )
        assert db_session.get(ChatResponseCheckpoint, response_id) is None
    status = _status(admin_user, chat_session_id)
    assert not status["is_processing"] and status["current_stream"] is None
    accepted = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Another question.",
        user_performing_action=admin_user,
    )
    assert accepted.error is None and accepted.full_message == "Second answer."
    # The model never got a result for the call: the continuation never ran.
    assert all(
        CALL_ID not in request.tool_result_ids()
        for request in mock_llm.requests_in("chat")
    )


def test_a_stop_while_the_turn_waits_leaves_its_request_to_decide(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """A waiting turn already stopped and runs nothing, so Stop finds no turn
    to stop: the request still waits, and its decision continues the
    response."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    chat_session_id = new_chat()
    stopped: list[int] = []

    def stop_then_approve(_packet: Packet, request: ToolApprovalRequest) -> None:
        # Web sends no stream ID; the CLI sends the ID of the stream that
        # stopped, which is the response's.
        stopped.extend(
            client.post(
                f"{API_SERVER_URL}/chat/stop-chat-session/{chat_session_id}",
                params={"stream_id": stream_id} if stream_id else None,
                headers=admin_user.headers,
                cookies=admin_user.cookies,
            ).status_code
            for stream_id in (None, _response_of(request.approval_id))
        )
        with get_session_with_current_tenant() as db_session:
            assert (
                db_session.get_one(ApprovalRequest, UUID(request.approval_id)).decision
                is None
            )
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    streams = _converse(
        streaming_api, admin_user, _request(chat_session_id), stop_then_approve
    )

    assert stopped == [200, 200]
    assert len(streams) == 2 and streams[-1][-1].obj == OverallStop(
        stop_reason="finished"
    )
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and "Hello, team!" in tool_result


def test_a_program_that_waits_for_approval_pauses_and_continues(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In code mode, a program's gated call shows its card on the program's
    card; the program parks, its dump is saved with the run, and after the
    decision it continues with its earlier output and both results."""
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", True)
    _set_policies(
        connected_mcp_server,
        admin_user,
        action_policies={"get_ticket": ActionPolicy.ALWAYS.value},
    )
    hello = connected_mcp_server.callable_name("hello")
    get_ticket = connected_mcp_server.callable_name("get_ticket")
    # Programs call the tools by their Python identifiers.
    hello_function, ticket_function = (
        function_name(name) for name in (hello, get_ticket)
    )
    code = (
        "print('started')\n"
        f"ticket, greeting = await asyncio.gather({ticket_function}(ticket_id=7), "
        f"{hello_function}(name='team'))\n"
        "print('ticket', ticket)\nprint('greeting', greeting)\n"
    )
    program = ToolCall(id="program", name="execute_code", arguments={"code": code})
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[program],
            conditions=RequestConditions(offers=["execute_code"]),
        ),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=["program"])),
    )
    chat_session_id = new_chat(["hello", "get_ticket"])
    dumps: list[int] = []

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        dumps.append(
            len(
                get_default_file_store().list_files_by_prefix(
                    f"agent-checkpoint/{chat_session_id}/"
                )
            )
        )
        _decide(admin_user, request.approval_id, "approve_once").raise_for_status()

    first, continued = _converse(
        streaming_api, admin_user, _request(chat_session_id), on_request
    )

    [(request_packet, request)] = _waiting(first)
    assert request.tool_name == hello
    # The program's second call, inside the program's card.
    assert request.tool_call_id == "program:1"
    starts = [
        packet.placement for packet in first if packet.obj.type == "code_mode_start"
    ]
    assert request_packet.placement in starts
    assert dumps == [1]
    result = mock_llm.requests_in("chat")[-1].tool_result("program")
    assert result is not None
    assert "started" in result
    assert "widget" in result and "Hello, team!" in result
    assert "Execution completed" in result
    assert _of_type(continued, ToolApprovalResolved) == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome="approved")
    ]
    # The continuation loaded the dump and deleted it.
    assert (
        get_default_file_store().list_files_by_prefix(
            f"agent-checkpoint/{chat_session_id}/"
        )
        == []
    )


def test_an_always_tool_runs_at_once(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    _set_policies(
        connected_mcp_server,
        admin_user,
        action_policies={"hello": ActionPolicy.ALWAYS.value},
    )
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )

    response = ChatSessionManager.send_message(
        chat_session_id=new_chat(),
        message="Say hello.",
        user_performing_action=admin_user,
    )

    assert response.error is None
    assert response.full_message == "Done."
    assert not any(
        packet["obj"]["type"] in {"tool_approval_request", "tool_approval_resolved"}
        for packet in response.packets
    )
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


@pytest.mark.parametrize("origin", [MessageOrigin.SLACKBOT, MessageOrigin.DISCORDBOT])
def test_a_user_who_claims_a_bot_origin_still_asks(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    origin: MessageOrigin,
) -> None:
    """The request's origin is client-supplied, so it cannot skip approvals."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    asked: list[str] = []

    def reject(_packet: Packet, request: ToolApprovalRequest) -> None:
        asked.append(request.approval_id)
        _decide(admin_user, request.approval_id, "reject").raise_for_status()

    _converse(
        streaming_api,
        admin_user,
        _request(new_chat()).model_copy(update={"origin": origin}),
        reject,
    )

    assert len(asked) == 1
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and "The user rejected this" in tool_result


def test_the_discord_bot_runs_tools_that_would_ask(
    connected_mcp_server: ConnectedMCPServer,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """Discord cannot show approval requests; its service API key, not a
    request field, lets its turns run ASK tools without asking."""
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    persona = PersonaManager.create(
        tool_ids=[connected_mcp_server.tool_ids["hello"]],
        user_performing_action=admin_user,
    )
    # The bot sends this request, as onyxbot/discord/api_client.py does.
    request = SendMessageRequest(
        message="Say hello.",
        stream=False,
        origin=MessageOrigin.DISCORDBOT,
        chat_session_info=ChatSessionCreationRequest(persona_id=persona.id),
    )
    with get_session_with_current_tenant() as db_session:
        created = get_discord_service_api_key(db_session) is None
        api_key = get_or_create_discord_service_api_key(
            db_session, POSTGRES_DEFAULT_SCHEMA
        )
        db_session.commit()
    try:
        sent = client.post(
            f"{API_SERVER_URL}/chat/send-chat-message",
            json=request.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        sent.raise_for_status()
        response = ChatFullResponse.model_validate(sent.json())
        assert response.chat_session_id is not None
        with get_session_with_current_tenant() as db_session:
            delete_chat_session(
                None, response.chat_session_id, db_session, hard_delete=True
            )
    finally:
        PersonaManager.delete(persona, admin_user)
        if created:
            with get_session_with_current_tenant() as db_session:
                delete_discord_service_api_key(db_session)
                db_session.commit()

    assert response.pending_tool_approvals == []
    assert response.answer == "Done."
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


def test_a_key_with_the_discord_bot_name_still_asks(
    connected_mcp_server: ConnectedMCPServer,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """Only the bot's own key skips approvals: a key that an admin names like
    it still asks."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    # As the admin API creates a key, with the bot key's groups (none).
    with get_session_with_current_tenant() as db_session:
        key = insert_api_key(
            db_session,
            APIKeyArgs(name=DISCORD_SERVICE_API_KEY_NAME),
            UUID(admin_user.id),
        )
    key_headers = {"Authorization": f"Bearer {key.api_key}"}
    persona = PersonaManager.create(
        tool_ids=[connected_mcp_server.tool_ids["hello"]],
        user_performing_action=admin_user,
    )
    try:
        sent = client.post(
            f"{API_SERVER_URL}/chat/send-chat-message",
            json=SendMessageRequest(
                message="Say hello.",
                stream=False,
                chat_session_info=ChatSessionCreationRequest(persona_id=persona.id),
            ).model_dump(mode="json"),
            headers=key_headers,
        )
        sent.raise_for_status()
        response = ChatFullResponse.model_validate(sent.json())
        assert response.chat_session_id is not None
        [pending] = response.pending_tool_approvals
        client.post(
            f"{API_SERVER_URL}/chat/approvals/{pending.approval_id}/decision",
            json={"decision": "reject"},
            headers=key_headers,
        ).raise_for_status()
        answer = _saved_answer(
            response.chat_session_id, response.message_id, "Done.", headers=key_headers
        )
        with get_session_with_current_tenant() as db_session:
            delete_chat_session(
                None, response.chat_session_id, db_session, hard_delete=True
            )
    finally:
        PersonaManager.delete(persona, admin_user)
        with get_session_with_current_tenant() as db_session:
            remove_api_key(db_session, key.api_key_id)
            db_session.commit()

    assert pending.tool_name == hello.name
    assert answer == "Done."


def test_a_turn_that_cannot_ask_runs_tools_that_would_ask(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """The Slack bot cannot show approval requests, so its turns run ASK tools
    without asking; disabled tools are still not offered."""
    _set_policies(
        connected_mcp_server,
        admin_user,
        action_policies={"get_ticket": ActionPolicy.DENY.value},
    )
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    get_ticket = connected_mcp_server.callable_name("get_ticket")
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[hello],
            conditions=RequestConditions(
                offers=[hello.name], does_not_offer=[get_ticket]
            ),
        ),
        Reply(text="Done.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    chat_session_id = new_chat(["hello", "get_ticket"])
    with get_session_with_current_tenant() as db_session:
        user = db_session.get_one(User, UUID(admin_user.id))

    # As onyxbot/slack/handlers/handle_regular_answer.py runs a turn.
    response = run_chat_turn(
        new_msg_req=_request(chat_session_id), user=user, ask_for_approval=False
    )

    assert response.pending_tool_approvals == []
    assert response.answer == "Done."
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


def test_a_non_streaming_request_returns_when_a_call_waits_for_approval(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """The response stops with the request to decide. After the decision it
    continues, and its answer reaches the chat."""
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(text="Greeted.", conditions=RequestConditions(has_results_for=[CALL_ID])),
    )
    chat_session_id = new_chat()

    early = client.post(
        f"{API_SERVER_URL}/chat/send-chat-message",
        json=_request(chat_session_id).model_dump(mode="json") | {"stream": False},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )

    early.raise_for_status()
    response = ChatFullResponse.model_validate(early.json())
    assert response.answer == "" and response.error_msg is None
    [pending] = response.pending_tool_approvals
    assert pending.model_dump(include={"tool_call_id", "tool_name", "arguments"}) == {
        "tool_call_id": CALL_ID,
        "tool_name": hello.name,
        "arguments": {"name": name},
    }

    _decide(admin_user, pending.approval_id, "approve_once").raise_for_status()

    assert (
        _saved_answer(
            chat_session_id,
            response.message_id,
            "Greeted.",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        == "Greeted."
    )
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


AGENT_CALL_ID = "agent_hello"


def _spawn(call_id: str, name: str, instruction: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=SPAWN_AGENT_TOOL_NAME,
        arguments={"name": name, "instruction": instruction},
    )


def _until(condition: Callable[[], bool], description: str) -> None:
    deadline = time.monotonic() + 60
    while not condition():
        assert time.monotonic() < deadline, f"Timed out waiting until {description}"
        time.sleep(0.25)


def _answers(user: DATestUser, chat_session_id: UUID) -> list[str]:
    detail = client.get(
        f"{API_SERVER_URL}/chat/get-chat-session/{chat_session_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    detail.raise_for_status()
    return [
        message["message"]
        for message in sorted(detail.json()["messages"], key=lambda m: m["message_id"])
        if message["message_type"] == "assistant"
    ]


def _parked(response_id: int) -> bool:
    with get_session_with_current_tenant() as db_session:
        response = db_session.get_one(ChatMessage, response_id)
        return (
            response.response_status == RunStatus.SUSPENDED
            and db_session.get(ChatResponseCheckpoint, response_id) is not None
            and bool(ownerless_response_ids(get_cache_backend(), [response_id]))
        )


def _agent_requests(
    user: DATestUser, chat_session_id: UUID
) -> list[tuple[Placement, PacketObj]]:
    return [
        (placement, packet)
        for placement, packet in _saved_approval_packets(user, chat_session_id)
        if isinstance(packet, ToolApprovalRequest) and packet.agent_name is not None
    ]


def _open_requests(chat_session_id: UUID) -> list[str]:
    with get_session_with_current_tenant() as db_session:
        return [
            str(approval_id)
            for approval_id in db_session.scalars(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.chat_session_id == chat_session_id,
                    ApprovalRequest.decision.is_(None),
                )
            )
        ]


def _waiting_agent_request(user: DATestUser, chat_session_id: UUID) -> str:
    """The one request that waits once the chat is idle, with its run parked.
    A parked agent waits for the user, so the status reports no active agent
    to poll for."""

    def parked() -> bool:
        status = _status(user, chat_session_id)
        approval_ids = _open_requests(chat_session_id)
        return (
            len(approval_ids) == 1
            and not status["is_processing"]
            and not status["has_active_subagents"]
            and _parked(_response_of(approval_ids[0]))
        )

    _until(parked, "the agent's run parks")
    [approval_id] = _open_requests(chat_session_id)
    return approval_id


@pytest.mark.parametrize(
    "decision, outcome",
    [("approve_once", "approved"), ("reject", "rejected")],
)
def test_an_agents_call_waits_durably_and_the_root_follows_up(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    decision: str,
    outcome: ToolApprovalOutcome,
) -> None:
    """A background agent's gated call parks the agent's run: no server or
    chat admission holds it, and sends still work. A reload shows its card in
    the root's spawn_agent card. After the decision the agent continues on any
    server, and its result wakes the root."""
    nonce = uuid4().hex
    task = f"Greet the team. {uuid4().hex}"
    hello = _hello(connected_mcp_server, AGENT_CALL_ID, "team")
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_spawn("spawn-mailer", "mailer", task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        Reply(
            text="Started the mailer.",
            conditions=RequestConditions(has_results_for=["spawn-mailer"]),
        ),
        Reply(
            text="The mailer reported.",
            conditions=RequestConditions(prompt_contains=["Mailer report"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        task,
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(
            text="Mailer report.",
            conditions=RequestConditions(has_results_for=[AGENT_CALL_ID]),
        ),
        conditions=RequestConditions(prompt_contains=[task]),
    )
    mock_llm.conversation(
        "second",
        Reply(text="Second answer."),
        conditions=RequestConditions(prompt_contains=["Another question."]),
    )
    chat_session_id = new_chat()
    started = ChatSessionManager.send_message(
        chat_session_id, f"Greet them. {nonce}", admin_user, accepts_follow_ups=True
    )
    assert started.error is None and started.full_message == "Started the mailer."

    approval_id = _waiting_agent_request(admin_user, chat_session_id)
    agent_response_id = _response_of(approval_id)
    assert agent_response_id != started.assistant_message_id
    [(_placement, request)] = _agent_requests(admin_user, chat_session_id)
    assert isinstance(request, ToolApprovalRequest)
    assert request.model_dump(
        include={"approval_id", "tool_name", "arguments", "agent_name"}
    ) == {
        "approval_id": approval_id,
        "tool_name": hello.name,
        "arguments": {"name": "team"},
        "agent_name": "mailer",
    }
    # A waiting agent does not block sends.
    second = ChatSessionManager.send_message(
        chat_session_id, "Another question.", admin_user, accepts_follow_ups=True
    )
    assert second.error is None and second.full_message == "Second answer."

    _decide(admin_user, approval_id, decision).raise_for_status()

    def followed_up() -> bool:
        status = _status(admin_user, chat_session_id)
        return (
            "The mailer reported." in _answers(admin_user, chat_session_id)
            and not status["is_processing"]
            and not status["has_active_subagents"]
        )

    _until(followed_up, "the root answers the agent's result")
    tool_result = mock_llm.requests_in(task)[-1].tool_result(AGENT_CALL_ID)
    assert tool_result is not None
    if outcome == "approved":
        assert "Hello, team!" in tool_result
    else:
        assert tool_result == (
            f"The user rejected this {hello.name} call, so it did not run."
        )
    with get_session_with_current_tenant() as db_session:
        assert db_session.get(ChatResponseCheckpoint, agent_response_id) is None
        assert (
            db_session.get_one(ChatMessage, agent_response_id).response_status
            == RunStatus.COMPLETE
        )
    assert _open_requests(chat_session_id) == []
    assert (
        _placement,
        ToolApprovalResolved(approval_id=approval_id, outcome=outcome),
    ) in _saved_approval_packets(admin_user, chat_session_id)


def test_an_agent_of_an_agent_resumes_first_then_its_parent(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """Root -> planner -> mailer, where the mailer asks: the planner waits for
    the mailer and parks after it. After the decision the mailer finishes
    first, then the planner, then the root follows up. The card shows in the
    root's call that started the planner."""
    nonce = uuid4().hex
    planner_task = f"Plan the greeting. {uuid4().hex}"
    mailer_task = f"Send the greeting. {uuid4().hex}"
    hello = _hello(connected_mcp_server, AGENT_CALL_ID, "team")
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_spawn("spawn-planner", "planner", planner_task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        Reply(
            text="Started the planner.",
            conditions=RequestConditions(has_results_for=["spawn-planner"]),
        ),
        Reply(
            text="The planner reported.",
            conditions=RequestConditions(prompt_contains=["Planner report"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        planner_task,
        Reply(
            tool_calls=[_spawn("spawn-mailer", "mailer", mailer_task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        # The planner answers, then waits for its agent before it finishes.
        Reply(
            text="Waiting for the mailer.",
            conditions=RequestConditions(has_results_for=["spawn-mailer"]),
        ),
        Reply(
            text="Planner report.",
            conditions=RequestConditions(prompt_contains=["Mailer report"]),
        ),
        conditions=RequestConditions(prompt_contains=[planner_task]),
    )
    mock_llm.conversation(
        mailer_task,
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(
            text="Mailer report.",
            conditions=RequestConditions(has_results_for=[AGENT_CALL_ID]),
        ),
        conditions=RequestConditions(prompt_contains=[mailer_task]),
    )
    chat_session_id = new_chat()
    started = ChatSessionManager.send_message(
        chat_session_id, f"Greet them. {nonce}", admin_user, accepts_follow_ups=True
    )
    assert started.full_message == "Started the planner."

    approval_id = _waiting_agent_request(admin_user, chat_session_id)
    mailer_response_id = _response_of(approval_id)
    with get_session_with_current_tenant() as db_session:
        planner_response_id = db_session.scalar(
            select(ChatMessage.id)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatSession.agent_name == "planner",
                ChatMessage.response_status.is_not(None),
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
    assert planner_response_id is not None
    _until(lambda: _parked(planner_response_id), "the planner parks")
    [(_placement, request)] = _agent_requests(admin_user, chat_session_id)
    assert isinstance(request, ToolApprovalRequest)
    assert request.agent_name == "mailer"

    _decide(admin_user, approval_id, "approve_once").raise_for_status()

    def followed_up() -> bool:
        status = _status(admin_user, chat_session_id)
        return (
            "The planner reported." in _answers(admin_user, chat_session_id)
            and not status["is_processing"]
            and not status["has_active_subagents"]
        )

    _until(followed_up, "the root answers the planner's result")
    with get_session_with_current_tenant() as db_session:
        mailer = db_session.get_one(ChatMessage, mailer_response_id)
        planner = db_session.get_one(ChatMessage, planner_response_id)
        assert mailer.response_status == planner.response_status == RunStatus.COMPLETE
        # The planner continued in the same run after the mailer ended.
        assert planner.message == "Planner report."
    tool_result = mock_llm.requests_in(mailer_task)[-1].tool_result(AGENT_CALL_ID)
    assert tool_result is not None and "Hello, team!" in tool_result


def test_stop_subagents_ends_a_parked_agent_with_the_users_rejection(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    nonce = uuid4().hex
    task = f"Greet the team. {uuid4().hex}"
    hello = _hello(connected_mcp_server, AGENT_CALL_ID, "team")
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_spawn("spawn-mailer", "mailer", task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        Reply(
            text="Started the mailer.",
            conditions=RequestConditions(has_results_for=["spawn-mailer"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        task,
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        conditions=RequestConditions(prompt_contains=[task]),
    )
    chat_session_id = new_chat()
    ChatSessionManager.send_message(
        chat_session_id, f"Greet them. {nonce}", admin_user, accepts_follow_ups=True
    )
    approval_id = _waiting_agent_request(admin_user, chat_session_id)
    agent_response_id = _response_of(approval_id)

    stopped = client.post(
        f"{API_SERVER_URL}/chat/chat-session/{chat_session_id}/stop-subagents",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    stopped.raise_for_status()
    assert stopped.json()["stopped_count"] == 1

    assert _open_requests(chat_session_id) == []
    assert not _status(admin_user, chat_session_id)["has_active_subagents"]
    with get_session_with_current_tenant() as db_session:
        row = db_session.get_one(ApprovalRequest, UUID(approval_id))
        assert (row.decision, row.decided_via) == (
            ApprovalDecision.REJECTED,
            ApprovalDecidedVia.USER,
        )
        assert (
            db_session.get_one(ChatMessage, agent_response_id).response_status
            == RunStatus.CANCELLED
        )
        assert db_session.get(ChatResponseCheckpoint, agent_response_id) is None
    # The call never ran: the agent made no request after its call.
    assert len(mock_llm.requests_in(task)) == 1
    assert _decide(admin_user, approval_id, "approve_once").status_code == 409


def test_a_root_stop_keeps_its_agents_request(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """An agent that asks while its root still streams changes the chat's
    approvals version, and a reload shows its card in the root's spawn_agent
    card. The user's Stop ends the root only; the agent keeps waiting for its
    decision."""
    nonce = uuid4().hex
    task = f"Greet the team. {uuid4().hex}"
    hello = _hello(connected_mcp_server, AGENT_CALL_ID, "team")
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_spawn("spawn-mailer", "mailer", task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        Reply(
            text="Still working",
            conditions=RequestConditions(has_results_for=["spawn-mailer"]),
            pause_after_first_chunk="root",
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        task,
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        conditions=RequestConditions(prompt_contains=[task]),
    )
    chat_session_id = new_chat()
    before = _status(admin_user, chat_session_id)["approvals_version"]
    packets: list[Packet] = []
    request = SendMessageRequest(
        chat_session_id=chat_session_id,
        message=f"Greet them. {nonce}",
        parent_message_id=None,
        accepts_follow_ups=True,
    )

    def read_stream() -> None:
        with httpx.Client(
            base_url=streaming_api,
            headers=admin_user.headers,
            cookies=admin_user.cookies,
            timeout=60,
        ) as http:
            with http.stream(
                "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
            ) as response:
                # Appended one by one: the test reads them while they arrive.
                packets.extend(_packets(response))

    reader = threading.Thread(target=read_stream)
    reader.start()
    try:
        _until(
            lambda: len(_open_requests(chat_session_id)) == 1,
            "the agent asks",
        )
        status = _status(admin_user, chat_session_id)
        assert status["is_processing"]
        assert status["approvals_version"] != before
        client.post(
            f"{API_SERVER_URL}/chat/stop-chat-session/{chat_session_id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()
        # The Stop ends the root while its model call still streams.
        _until(lambda: _stop_reason(packets) is not None, "the root stops")
    finally:
        mock_llm.release_gate("root")
        reader.join(timeout=60)
    # The root stopped; its stream had no card for the agent's request.
    assert _stop_reason(packets) == "user_cancelled"
    assert not _of_type(packets, ToolApprovalRequest)
    with get_session_with_current_tenant() as db_session:
        root = db_session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.response_status.is_not(None),
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        assert root is not None and root.response_status == RunStatus.CANCELLED

    approval_id = _waiting_agent_request(admin_user, chat_session_id)
    with get_session_with_current_tenant() as db_session:
        assert db_session.get_one(ApprovalRequest, UUID(approval_id)).decision is None
    [(placement, card)] = _agent_requests(admin_user, chat_session_id)
    assert isinstance(card, ToolApprovalRequest)
    assert card.approval_id == approval_id
    assert card.agent_name == "mailer" and card.arguments == {"name": "team"}
    # The card is in the spawn_agent card: the tool card of the root's call.
    assert any(
        packet.placement.model_copy(update={"model_index": 0}) == placement
        for packet in packets
    )


def test_a_program_in_an_agent_parks_and_continues(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In code mode, an agent's program call parks the program with the
    agent's run; its dump is saved under the root chat's prefix, and after the
    decision the program continues and the root follows up."""
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", True)
    nonce = uuid4().hex
    task = f"Greet the team. {uuid4().hex}"
    hello_function = function_name(connected_mcp_server.callable_name("hello"))
    code = (
        "print('started')\n"
        f"greeting = await {hello_function}(name='team')\n"
        "print('greeting', greeting)\n"
    )
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_spawn("spawn-mailer", "mailer", task)],
            conditions=RequestConditions(offers=[SPAWN_AGENT_TOOL_NAME]),
        ),
        Reply(
            text="Started the mailer.",
            conditions=RequestConditions(has_results_for=["spawn-mailer"]),
        ),
        Reply(
            text="The mailer reported.",
            conditions=RequestConditions(prompt_contains=["Mailer report"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        task,
        Reply(
            tool_calls=[
                ToolCall(id="program", name="execute_code", arguments={"code": code})
            ],
            conditions=RequestConditions(offers=["execute_code"]),
        ),
        Reply(
            text="Mailer report.",
            conditions=RequestConditions(has_results_for=["program"]),
        ),
        conditions=RequestConditions(prompt_contains=[task]),
    )
    chat_session_id = new_chat()
    prefix = f"agent-checkpoint/{chat_session_id}/"
    ChatSessionManager.send_message(
        chat_session_id, f"Greet them. {nonce}", admin_user, accepts_follow_ups=True
    )
    approval_id = _waiting_agent_request(admin_user, chat_session_id)
    assert len(get_default_file_store().list_files_by_prefix(prefix)) == 1
    [(_placement, request)] = _agent_requests(admin_user, chat_session_id)
    assert isinstance(request, ToolApprovalRequest)
    # The program's call shows its arguments, saved with the request.
    assert request.agent_name == "mailer" and request.arguments == {"name": "team"}

    _decide(admin_user, approval_id, "approve_once").raise_for_status()

    def followed_up() -> bool:
        status = _status(admin_user, chat_session_id)
        return (
            "The mailer reported." in _answers(admin_user, chat_session_id)
            and not status["is_processing"]
            and not status["has_active_subagents"]
        )

    _until(followed_up, "the root answers the agent's result")
    result = mock_llm.requests_in(task)[-1].tool_result("program")
    assert result is not None
    assert "started" in result and "Hello, team!" in result
    # The checkpoint owned the dump, which went when the agent's response ended.
    assert get_default_file_store().list_files_by_prefix(prefix) == []
