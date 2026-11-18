"""The root chat agent asks the user questions through the real chat API: the
stream stops while a question waits, an answer from the card or a typed
message continues the response in a new stream, and a reload shows the
question's record."""

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx

from onyx.server.query_and_chat.models import CurrentStreamInfo, SendMessageRequest
from onyx.server.query_and_chat.streaming_models import (
    AWAITING_USER,
    AgentResponseDelta,
    CustomToolDelta,
    OverallStop,
    Packet,
    PacketObj,
    ToolQuestionRequest,
    ToolQuestionResolved,
)
from onyx.tools.constants import (
    ASK_USER_QUESTION_TOOL_NAME,
    REQUEST_USER_INPUT_TOOL_NAME,
    SPAWN_AGENT_TOOL_NAME,
)
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

CALL_ID = "call_ask"
QUESTIONS = [
    {
        "id": "scope",
        "header": "Scope",
        "question": "Who should get the email?",
        "options": [
            {"label": "Team (Recommended)", "description": "Only the team."},
            {"label": "Company", "description": "Everyone."},
        ],
    }
]


def _script(
    mock_llm: MockLLMScript, nonce: str, answer: str, call_ids: tuple[str, ...]
) -> None:
    """The model asks with one question call per ID, then answers once it has
    their results."""
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id=call_id,
                    name=REQUEST_USER_INPUT_TOOL_NAME,
                    arguments={"questions": QUESTIONS},
                )
                for call_id in call_ids
            ],
            conditions=RequestConditions(offers=[REQUEST_USER_INPUT_TOOL_NAME]),
        ),
        Reply(
            text=answer, conditions=RequestConditions(has_results_for=list(call_ids))
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )


def _result(mock_llm: MockLLMScript, nonce: str, call_id: str) -> str | None:
    """The result of `call_id` that the model's last request read."""
    return mock_llm.requests_in(nonce)[-1].tool_result(call_id)


def _packets(response: httpx.Response) -> Iterator[PacketObj]:
    response.raise_for_status()
    for line in response.iter_lines():
        data = json.loads(line) if line else {}
        if "obj" in data:
            yield Packet.model_validate(data).obj


def _send(http: httpx.Client, chat_session_id: UUID, message: str) -> list[PacketObj]:
    request = SendMessageRequest(chat_session_id=chat_session_id, message=message)
    with http.stream(
        "POST", "/chat/send-chat-message", json=request.model_dump(mode="json")
    ) as response:
        return list(_packets(response))


def _follow(
    http: httpx.Client, chat_session_id: UUID, continuation: dict[str, object]
) -> list[PacketObj]:
    stream = CurrentStreamInfo.model_validate(continuation)
    with http.stream(
        "GET",
        f"/chat/chat-session/{chat_session_id}/resume-stream",
        params={"cursor": 0, "stream_id": stream.stream_id},
    ) as response:
        return list(_packets(response))


def _saved(http: httpx.Client, chat_session_id: UUID) -> list[PacketObj]:
    detail = http.get(f"/chat/get-chat-session/{chat_session_id}")
    detail.raise_for_status()
    return [
        Packet.model_validate(packet).obj
        for response in detail.json()["packets"]
        for packet in response
    ]


def _stops(packets: list[PacketObj]) -> list[str | None]:
    return [packet.stop_reason for packet in packets if isinstance(packet, OverallStop)]


def _of_type[T](packets: list[PacketObj], kind: type[T]) -> list[T]:
    return [packet for packet in packets if isinstance(packet, kind)]


def _http(streaming_api: str, user: DATestUser) -> httpx.Client:
    return httpx.Client(
        base_url=streaming_api, headers=user.headers, cookies=user.cookies, timeout=60
    )


def test_a_card_answer_continues_the_response(
    admin_user: DATestUser,
    basic_user: DATestUser,
    mock_llm: MockLLMScript,
    streaming_api: str,
) -> None:
    """The stream stops while the question waits, and a send is refused. The
    card's answer continues the response in a new stream, the model reads the
    answers, and a reload shows how the question ended. Repeating the answer
    returns it; another answer is a conflict, and another user cannot find
    the question."""
    nonce = uuid4().hex
    _script(mock_llm, nonce, "Emailing the company.", (CALL_ID,))
    session = ChatSessionManager.create(user_performing_action=admin_user)
    with _http(streaming_api, admin_user) as http:
        first = _send(http, session.id, f"Email the team. {nonce}")
        assert _stops(first) == [AWAITING_USER]
        [asked] = _of_type(first, ToolQuestionRequest)
        assert asked.tool_call_id == CALL_ID
        assert [question.id for question in asked.questions] == ["scope"]
        assert _of_type(_saved(http, session.id), ToolQuestionRequest) == [asked]

        blocked = http.post(
            "/chat/send-chat-message",
            json=SendMessageRequest(
                chat_session_id=session.id, message="Hello?", stream=False
            ).model_dump(mode="json"),
        )
        assert blocked.status_code == 409
        assert blocked.json()["error_code"] == "APPROVAL_PENDING"

        url = f"/chat/question-requests/{asked.question_request_id}/answers"
        body = {
            "answers": [
                {"question_id": "scope", "option_label": "Company", "user_note": "EU"}
            ]
        }
        with _http(streaming_api, basic_user) as other_user:
            assert other_user.post(url, json=body).status_code == 404
        answered = http.post(url, json=body)
        answered.raise_for_status()
        continuation = answered.json()["continuation"]
        assert continuation is not None
        continued = _follow(http, session.id, continuation)
        assert _stops(continued)[-1] == "finished"
        # The call shows only its card: no generic tool output.
        assert not _of_type(continued, CustomToolDelta)
        assert (
            "".join(
                packet.content for packet in _of_type(continued, AgentResponseDelta)
            )
            == "Emailing the company."
        )
        assert _result(mock_llm, nonce, CALL_ID) == json.dumps(
            {"answers": {"scope": {"answers": ["Company", "user_note: EU"]}}}
        )

        assert http.post(url, json=body).status_code == 200
        other = http.post(
            url,
            json={
                "answers": [
                    {"question_id": "scope", "option_label": "Team (Recommended)"}
                ]
            },
        )
        assert other.status_code == 409
        [resolved] = _of_type(_saved(http, session.id), ToolQuestionResolved)
        assert (resolved.outcome, resolved.answered_via) == ("answered", "card")


def _ask(call_id: str) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=REQUEST_USER_INPUT_TOOL_NAME,
        arguments={"questions": QUESTIONS},
    )


def test_a_typed_message_answers_every_waiting_question(
    admin_user: DATestUser, mock_llm: MockLLMScript, streaming_api: str
) -> None:
    """Two calls ask. The card answers the first, and the response still
    waits. A message that the user types, sent for the first question,
    answers the second; the model reads it as the user typed it, and the
    record keeps it so the chat shows it as the user's message. The
    continued response asks again; a retry of the message returns it and
    answers nothing new."""
    nonce = uuid4().hex
    typed = "Only Ana and Raj, please."
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[_ask("call_first"), _ask("call_second")],
            conditions=RequestConditions(offers=[REQUEST_USER_INPUT_TOOL_NAME]),
        ),
        Reply(
            tool_calls=[_ask("call_third")],
            conditions=RequestConditions(has_results_for=["call_first", "call_second"]),
        ),
        Reply(
            text="Emailing Ana and Raj.",
            conditions=RequestConditions(has_results_for=["call_third"]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    with _http(streaming_api, admin_user) as http:
        first, second = sorted(
            _of_type(
                _send(http, session.id, f"Email the team. {nonce}"),
                ToolQuestionRequest,
            ),
            key=lambda asked: asked.tool_call_id,
        )
        first_url = f"/chat/question-requests/{first.question_request_id}/answers"
        card = {"answers": [{"question_id": "scope", "option_label": "Company"}]}
        answered = http.post(first_url, json=card)
        answered.raise_for_status()
        assert answered.json()["continuation"] is None

        answered = http.post(first_url, json={"message": typed})
        answered.raise_for_status()
        continued = _follow(http, session.id, answered.json()["continuation"])
        assert _stops(continued)[-1] == AWAITING_USER
        # The replayed prefix and the live call each report how it ended.
        resolved = {
            packet.question_request_id: packet
            for packet in _of_type(continued, ToolQuestionResolved)
        }
        assert resolved[first.question_request_id].answered_via == "card"
        assert (
            resolved[second.question_request_id].answered_via,
            resolved[second.question_request_id].message,
        ) == ("message", typed)
        assert _result(mock_llm, nonce, "call_first") == json.dumps(
            {"answers": {"scope": {"answers": ["Company"]}}}
        )
        assert _result(mock_llm, nonce, "call_second") == typed
        [third] = [
            asked
            for asked in _of_type(continued, ToolQuestionRequest)
            if asked.tool_call_id == "call_third"
        ]

        retried = http.post(first_url, json={"message": typed})
        assert retried.status_code == 200
        assert retried.json()["continuation"] is None
        saved = {
            packet.question_request_id
            for packet in _of_type(_saved(http, session.id), ToolQuestionResolved)
        }
        assert third.question_request_id not in saved

        third_url = f"/chat/question-requests/{third.question_request_id}/answers"
        answered = http.post(third_url, json=card)
        answered.raise_for_status()
        finished = _follow(http, session.id, answered.json()["continuation"])
        assert _stops(finished)[-1] == "finished"


def test_agents_that_the_root_starts_get_no_question_tool(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """The root offers the question tool; a background agent cannot ask the
    user."""
    nonce = uuid4().hex
    child_task = f"Look this up. {uuid4().hex}"
    mock_llm.conversation(
        nonce,
        Reply(
            tool_calls=[
                ToolCall(
                    id="spawn-lookup",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"name": "lookup", "instruction": child_task},
                )
            ],
            conditions=RequestConditions(
                offers=[SPAWN_AGENT_TOOL_NAME, REQUEST_USER_INPUT_TOOL_NAME]
            ),
        ),
        Reply(
            text="Looking it up.",
            conditions=RequestConditions(has_results_for=["spawn-lookup"]),
        ),
        Reply(
            text="Found it.",
            conditions=RequestConditions(prompt_contains=["Lookup done."]),
        ),
        conditions=RequestConditions(prompt_contains=[nonce]),
    )
    mock_llm.conversation(
        child_task,
        Reply(
            text="Lookup done.",
            conditions=RequestConditions(
                does_not_offer=[
                    REQUEST_USER_INPUT_TOOL_NAME,
                    ASK_USER_QUESTION_TOOL_NAME,
                ]
            ),
        ),
        conditions=RequestConditions(prompt_contains=[child_task]),
    )
    session = ChatSessionManager.create(user_performing_action=admin_user)
    started = ChatSessionManager.send_message(
        session.id, f"Look it up. {nonce}", admin_user, accepts_follow_ups=True
    )
    assert started.error is None
    mock_llm.wait_for_requests(
        nonce, 3, timeout=60, failure_message="the root never read the agent's result"
    )
    assert [request.error for request in mock_llm.requests_in(child_task)] == [None]
