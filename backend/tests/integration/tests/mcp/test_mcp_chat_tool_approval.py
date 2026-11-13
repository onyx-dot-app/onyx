"""MCP tool calls in chat follow the action policies and wait for the user."""

import json
import time
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.chat.models import ChatFullResponse
from onyx.chat.process_message import run_chat_turn
from onyx.chat.tool_approvals import TOOL_APPROVAL_TIMEOUT
from onyx.configs.constants import DISCORD_SERVICE_API_KEY_NAME
from onyx.db.api_key import insert_api_key, remove_api_key
from onyx.db.approval_request import create_approval_request__no_commit
from onyx.db.chat import delete_chat_session
from onyx.db.discord_bot import (
    delete_discord_service_api_key,
    get_discord_service_api_key,
    get_or_create_discord_service_api_key,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ActionPolicy, ApprovalDecision
from onyx.db.models import ApprovalRequest, GatedApp, User
from onyx.server.api_key.models import APIKeyArgs
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    MessageOrigin,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    Packet,
    ToolApprovalOutcome,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
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


def _saved_answer(
    chat_session_id: UUID,
    message_id: int,
    expected: str,
    *,
    headers: dict[str, str],
    cookies: dict[str, str] | None = None,
) -> str | None:
    """The saved answer of a response that kept running after the request
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


def _stream(
    streaming_api: str,
    user: DATestUser,
    request: SendMessageRequest,
    on_request: OnRequest,
) -> list[Packet]:
    """Send a message over a real HTTP stream and call `on_request` for each
    approval request as it arrives; the run waits until it is decided."""
    packets: list[Packet] = []
    with httpx.Client(
        base_url=streaming_api,
        headers=user.headers,
        cookies=user.cookies,
        timeout=60,
    ) as http:
        with http.stream(
            "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
        ) as response:
            for packet in _packets(response):
                packets.append(packet)
                if isinstance(packet.obj, ToolApprovalRequest):
                    on_request(packet, packet.obj)
    return packets


def _of_type[T](packets: list[Packet], kind: type[T]) -> list[T]:
    return [packet.obj for packet in packets if isinstance(packet.obj, kind)]


@pytest.mark.parametrize(
    "decision, outcome",
    [("approve_once", "approved"), ("reject", "rejected")],
)
def test_a_call_waits_for_the_users_decision(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    basic_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
    decision: str,
    outcome: ToolApprovalOutcome,
) -> None:
    """With the default ASK policy, the stream asks for approval at the call's
    card, the call waits, and the decision runs or skips the tool. A decision
    is saved once."""
    name = uuid4().hex
    hello = _hello(connected_mcp_server, CALL_ID, name)
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        # The answer waits for the checks below, so the response keeps its owner.
        Reply(
            text="Done. All set.",
            conditions=RequestConditions(has_results_for=[CALL_ID]),
            pause_after_first_chunk="answer",
        ),
    )
    chat_session_id = new_chat()
    asked_at = datetime.now(timezone.utc)
    replayed: list[Packet] = []
    decisions: list[httpx.Response] = []

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
        # A client that resumes the stream sees the request at its placement.
        with httpx.Client(
            base_url=streaming_api,
            headers=admin_user.headers,
            cookies=admin_user.cookies,
            timeout=60,
        ) as http:
            with http.stream(
                "GET", f"/chat/chat-session/{chat_session_id}/resume-stream?cursor=0"
            ) as resumed:
                for replay in _packets(resumed):
                    if isinstance(replay.obj, ToolApprovalRequest):
                        replayed.append(replay)
                        break
        opposite = "approve_once" if decision == "reject" else "reject"
        decisions.extend(
            [
                _decide(admin_user, request.approval_id, decision),
                _decide(admin_user, request.approval_id, decision),
                _decide(admin_user, request.approval_id, opposite),
                _decide(basic_user, request.approval_id, decision),
            ]
        )
        mock_llm.release_gate("answer")

    try:
        packets = _stream(
            streaming_api, admin_user, _request(chat_session_id), on_request
        )
    finally:
        mock_llm.release_gate("answer")

    [request_packet] = [
        packet for packet in packets if isinstance(packet.obj, ToolApprovalRequest)
    ]
    request = request_packet.obj
    assert isinstance(request, ToolApprovalRequest)
    assert request.model_dump(include={"tool_call_id", "tool_name", "arguments"}) == {
        "tool_call_id": CALL_ID,
        "tool_name": hello.name,
        "arguments": {"name": name},
    }
    assert request.display_name
    assert (
        asked_at + TOOL_APPROVAL_TIMEOUT - timedelta(seconds=5)
        <= request.expires_at
        <= datetime.now(timezone.utc) + TOOL_APPROVAL_TIMEOUT
    )
    assert [(packet.placement, packet.obj) for packet in replayed] == [
        (request_packet.placement, request)
    ]
    # The call's card starts, asks, shows the decision, then any result.
    card = [
        packet.obj.type
        for packet in packets
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
    assert _of_type(packets, ToolApprovalResolved) == [
        ToolApprovalResolved(approval_id=request.approval_id, outcome=outcome)
    ]

    # Repeating the decision returns it; the opposite one conflicts; another
    # user cannot see the request.
    saved = {
        "approval_id": request.approval_id,
        "decision": outcome.upper(),
        "decided_via": "USER",
    }
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
        assert "The user rejected this" in tool_result


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

    packets = _stream(
        streaming_api,
        admin_user,
        _request(new_chat()),
        on_request,
    )

    assert [
        (decision["decision"], decision["decided_via"]) for decision in decisions
    ] == [("REJECTED", "POLICY")]
    assert [
        resolved.outcome for resolved in _of_type(packets, ToolApprovalResolved)
    ] == ["disabled"]
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None
    assert "The hello tool is disabled" in tool_result and "Hello" not in tool_result


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

    _stream(
        streaming_api,
        admin_user,
        _request(new_chat()),
        on_request,
    )

    assert len(asked) == (0 if users_can_manage else 1)
    tool_result = mock_llm.requests_in("chat")[-1].tool_result(CALL_ID)
    assert tool_result is not None and f"Hello, {name}!" in tool_result


def test_approving_for_the_chat_runs_waiting_and_later_calls(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
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

    def grant(_packet: Packet, request: ToolApprovalRequest) -> None:
        asked.append(request.approval_id)
        # Both calls wait, then the user approves the first for the chat.
        if len(asked) == 2:
            _decide(admin_user, asked[0], "approve_session").raise_for_status()

    packets = _stream(streaming_api, admin_user, _request(chat_session_id), grant)

    # The grant approves the waiting sibling too, and both cards say so.
    assert sorted(
        (resolved.approval_id, resolved.outcome)
        for resolved in _of_type(packets, ToolApprovalResolved)
    ) == sorted((approval_id, "approved_for_chat") for approval_id in asked)
    results = mock_llm.requests_in("chat")[-1]
    assert "Hello, a!" in (results.tool_result("call_a") or "")
    assert "Hello, b!" in (results.tool_result("call_b") or "")

    later_requests: list[str] = []

    def unexpected(_packet: Packet, request: ToolApprovalRequest) -> None:
        later_requests.append(request.approval_id)
        _decide(admin_user, request.approval_id, "reject").raise_for_status()

    later_packets = _stream(
        streaming_api,
        admin_user,
        _request(chat_session_id, "Say hello again.").model_copy(
            update={"parent_message_id": -1}
        ),
        unexpected,
    )

    assert later_requests == []
    assert _of_type(later_packets, ToolApprovalResolved) == []
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
    held_seconds = 6.0

    def on_request(_packet: Packet, request: ToolApprovalRequest) -> None:
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

    _stream(streaming_api, admin_user, _request(chat_session_id), on_request)

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
    assert first_answer["processing_duration_seconds"] is not None
    assert first_answer["processing_duration_seconds"] < held_seconds


def test_stopping_a_waiting_chat_ends_its_request(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """A stopped response no longer waits, so its request cannot be decided."""
    hello = _hello(connected_mcp_server, CALL_ID, "team")
    mock_llm.conversation(
        "chat",
        Reply(tool_calls=[hello], conditions=RequestConditions(offers=[hello.name])),
        Reply(
            text="Done.",
            conditions=RequestConditions(has_results_for=[CALL_ID]),
            required=False,
        ),
    )
    chat_session_id = new_chat()
    approval_ids: list[str] = []

    def stop(_packet: Packet, request: ToolApprovalRequest) -> None:
        approval_ids.append(request.approval_id)
        client.post(
            f"{API_SERVER_URL}/chat/stop-chat-session/{chat_session_id}",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        ).raise_for_status()

    packets = _stream(streaming_api, admin_user, _request(chat_session_id), stop)

    # The stream ends with the stop packet; it closes the card if the
    # "cancelled" end of the request did not come first.
    types = [packet.obj.type for packet in packets]
    assert "stop" in types[types.index("tool_approval_request") :]
    assert _of_type(packets, ToolApprovalResolved) in (
        [],
        [ToolApprovalResolved(approval_id=approval_ids[0], outcome="cancelled")],
    )
    decided = _decide(admin_user, approval_ids[0], "approve_once")
    assert decided.status_code == 409
    assert mock_llm.requests_in("chat")[-1].tool_result(CALL_ID) is None


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

    _stream(
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


@pytest.mark.parametrize("action", ["decide", "send"])
def test_a_request_whose_response_has_no_owner_expires_when_used(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
    action: str,
) -> None:
    """Nothing waits for a response whose owner is gone, e.g. after its server
    restarted: a decision conflicts, and a new message is not blocked."""
    mock_llm.conversation(
        "chat", Reply(text="First."), Reply(text="Second.", required=False)
    )
    chat_session_id = new_chat()
    finished = ChatSessionManager.send_message(
        chat_session_id=chat_session_id,
        message="Hi.",
        user_performing_action=admin_user,
    )
    with get_session_with_current_tenant() as db_session:
        approval_id, _created_at = create_approval_request__no_commit(
            db_session,
            chat_session_id=chat_session_id,
            chat_message_id=finished.assistant_message_id,
            gated_app_id=db_session.scalars(
                select(GatedApp.id).where(
                    GatedApp.mcp_server_id == connected_mcp_server.id
                )
            ).one(),
            action_id="hello",
        )
        db_session.commit()

    if action == "decide":
        assert _decide(admin_user, str(approval_id), "approve_once").status_code == 409
    else:
        second = ChatSessionManager.send_message(
            chat_session_id=chat_session_id,
            message="Again.",
            user_performing_action=admin_user,
        )
        assert second.error is None and second.full_message == "Second."

    with get_session_with_current_tenant() as db_session:
        assert db_session.get_one(ApprovalRequest, approval_id).decision == (
            ApprovalDecision.EXPIRED
        )


def test_a_non_streaming_request_returns_when_a_call_waits_for_approval(
    connected_mcp_server: ConnectedMCPServer,
    new_chat: NewChat,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """The complete response returns early with the request to decide. The
    turn keeps running, and its answer reaches the chat after the decision."""
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
