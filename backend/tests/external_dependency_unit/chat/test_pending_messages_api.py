"""Pending user messages remain editable until Chat accepts them for execution."""

import asyncio
from collections.abc import Generator
from threading import Event
from typing import override
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.models import (
    InputSource,
    MessageDelivery,
    RunStatus,
    agent_result_message_id,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.execution import chat_turn_work
from onyx.chat.models import PendingChatMessage
from onyx.chat.presentation import replay_response
from onyx.chat.process_message import (
    dispatch_pending_chat_messages,
    handle_stream_message_objects,
)
from onyx.chat.stop_signal_checker import request_stop
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat_inputs import consume_inputs__no_commit, read_run_inputs
from onyx.db.chat_response import read_response_record
from onyx.db.enums import HookPoint, IncognitoRecordMode
from onyx.db.models import ChatInput, ChatMessage, ChatSession, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.hooks.executor import HookSkipped
from onyx.hooks.points.query_processing import (
    QueryProcessingPayload,
    QueryProcessingResponse,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext, LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    GenerationStartEvent,
    TextContent,
    TextDeltaEvent,
    UserMessage,
)
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.streaming_models import UserMessagePacket
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.fixture
def owner(make_test_user: MakeTestUser) -> User:
    return make_test_user("pending-chat-owner")


@pytest.fixture
def chat(db_session: Session, owner: User) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Pending input",
    )
    db_session.add(chat)
    db_session.commit()
    return chat


@pytest.fixture
def response(db_session: Session, chat: ChatSession) -> ChatMessage:
    root = ChatMessage(
        chat_session_id=chat.id,
        message="",
        token_count=0,
        message_type=MessageType.SYSTEM,
    )
    db_session.add(root)
    db_session.flush()
    question = ChatMessage(
        parent_message_id=root.id,
        chat_session_id=chat.id,
        message="Initial question",
        token_count=2,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.flush()
    answer = ChatMessage(
        chat_session_id=chat.id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(answer)
    db_session.flush()
    root.latest_child_message_id = question.id
    question.latest_child_message_id = answer.id
    db_session.commit()
    return answer


@pytest.fixture
def app(db_session: Session, owner: User) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_backend.router)
    register_onyx_exception_handlers(app)
    for route in app.routes:
        if not isinstance(route, APIRoute) or "pending-messages" not in route.path:
            continue
        for dependency in route.dependant.dependencies:
            if dependency.name == "user":
                assert dependency.call is not None
                app.dependency_overrides[dependency.call] = lambda: owner
    app.dependency_overrides[chat_backend.check_token_rate_limits] = lambda: None
    app.dependency_overrides[chat_backend.check_api_key_usage] = lambda: None

    def request_session() -> Generator[Session, None, None]:
        with Session(db_session.get_bind()) as session:
            yield session

    app.dependency_overrides[chat_backend.get_session] = request_session
    return app


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
        assert chat_turn_work.wait_idle(timeout=30)


def test_promoting_prefetched_input_prevents_between_step_acceptance(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    submitted = client.post(
        path,
        json={
            "message": "Change direction",
            "delivery": "send",
            "target_response_id": response.id,
        },
    )
    assert submitted.status_code == 200, submitted.text
    message_id = submitted.json()["id"]
    messages = read_run_inputs(
        db_session, str(response.chat_session_id), str(response.id), [response.id], None
    )[0]
    assert len(messages) == 1
    db_session.rollback()
    promoted = client.post(f"{path}/{message_id}/interrupt")
    assert promoted.status_code == 200, promoted.text
    assert not consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    db_session.rollback()
    assert client.get(path).json() == [promoted.json()]


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.ERROR])
def test_late_send_is_queued_and_waits_after_unsuccessful_execution(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    status: RunStatus,
) -> None:
    response.response_status = status
    db_session.commit()
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    for delivery in ("send", "queue"):
        submitted = client.post(
            path,
            json={
                "message": "Next turn",
                "delivery": delivery,
                "target_response_id": response.id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        pending = PendingChatMessage.model_validate(submitted.json())
        assert pending.delivery == MessageDelivery.QUEUE
        assert pending.target_response_id is None
    assert chat_turn_work.wait_idle(timeout=10)
    assert len(client.get(path).json()) == 2
    assert (
        db_session.scalar(
            select(ChatMessage.id).where(ChatMessage.parent_message_id == response.id)
        )
        is None
    )


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("deleted", 404),
        ("child", 404),
        *((f"incognito_{mode.value}", 400) for mode in IncognitoRecordMode),
    ],
)
def test_queue_routes_reject_inaccessible_sessions(
    client: TestClient,
    owner: User,
    response: ChatMessage,
    db_session: Session,
    case: str,
    expected_status: int,
) -> None:
    chat_id = response.chat_session_id
    if case.startswith("incognito_"):
        response.chat_session.incognito_record_mode = IncognitoRecordMode(
            case.removeprefix("incognito_")
        )
    else:
        chat = ChatSession(
            id=uuid4(),
            user_id=owner.id,
            spawned_by_message_id=response.id if case == "child" else None,
            deleted=case == "deleted",
        )
        db_session.add(chat)
        chat_id = chat.id
    db_session.commit()
    path = f"/chat/chat-session/{chat_id}/pending-messages"
    assert client.get(path).status_code == expected_status
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == expected_status
    )
    assert client.delete(f"{path}/unknown").status_code == expected_status
    assert client.post(f"{path}/unknown/interrupt").status_code == expected_status


@pytest.mark.parametrize(
    "body",
    [
        {"message": " ", "delivery": "queue"},
        {
            "message": "text",
            "delivery": "queue",
            "mcp_headers": {"Authorization": "test"},
        },
        {"message": "text", "delivery": "queue", "target_response_id": -1},
    ],
)
def test_pending_input_rejects_invalid_or_transient_fields(
    client: TestClient,
    response: ChatMessage,
    body: dict[str, str | int | dict[str, str]],
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    assert client.post(path, json=body).status_code == 422


def test_send_targets_a_current_response(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    rejected = client.post(
        path,
        json={
            "message": "Invalid target",
            "delivery": "send",
            "target_response_id": response.parent_message_id,
        },
    )
    assert rejected.status_code == 409, rejected.text
    question = response.parent_message
    assert question is not None
    sibling = ChatMessage(
        chat_session_id=response.chat_session_id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(sibling)
    db_session.flush()
    question.latest_child_message_id = sibling.id
    db_session.commit()
    # Several models answer the same question; a send without a target goes to
    # the selected one.
    untargeted = client.post(path, json={"message": "Selected", "delivery": "send"})
    assert untargeted.status_code == 200, untargeted.text
    assert untargeted.json()["target_response_id"] == sibling.id
    sent = client.post(
        path,
        json={
            "message": "This one",
            "delivery": "send",
            "target_response_id": response.id,
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["target_response_id"] == response.id
    queued = client.post(path, json={"message": "Later", "delivery": "queue"})
    assert queued.status_code == 200, queued.text
    assert client.get(path).json() == [untargeted.json(), sent.json(), queued.json()]


def test_send_without_target_binds_to_the_only_running_regeneration(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    question = response.parent_message
    assert question is not None
    response.response_status = RunStatus.COMPLETE
    regeneration = ChatMessage(
        chat_session_id=response.chat_session_id,
        parent_message_id=question.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(regeneration)
    db_session.flush()
    question.latest_child_message_id = regeneration.id
    db_session.commit()
    sent = client.post(
        f"/chat/chat-session/{response.chat_session_id}/pending-messages",
        json={"message": "Steer", "delivery": "send"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["delivery"] == "send"
    assert sent.json()["target_response_id"] == regeneration.id


class QueueTestLLM(FakeModelClient):
    @property
    @override
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-4o-mini",
            max_input_tokens=32768,
            temperature=0,
        )


@pytest.mark.parametrize("promote", [False, True])
def test_interrupt_saves_partial_response_and_starts_before_queued_messages(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    promote: bool,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, cancelled, release = Event(), Event(), Event()
    requests: list[GenerationRequest] = []

    class InterruptibleModel(QueueTestLLM):
        @override
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            requests.append(request)
            if len(requests) != 1:
                yield from super().stream(request, context)
                return
            assert context is not None and context.cancellation is not None
            signal = context.cancellation
            yield GenerationStartEvent()
            yield TextDeltaEvent(content_index=0, text="Partial answer")
            with signal.on_cancel(cancelled.set):
                entered.set()
                assert release.wait(30)
            signal.check()
            pytest.fail("The first response must be interrupted")

    model = InterruptibleModel(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        response = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert response is not None
        next_step = client.post(
            path,
            json={
                "message": "Apply this next",
                "delivery": "send",
                "target_response_id": response.id,
            },
        )
        assert next_step.status_code == 200, next_step.text
        queued = client.post(
            path,
            json={
                "message": "Do this later",
                "delivery": "queue",
                "target_response_id": response.id,
            },
        )
        assert queued.status_code == 200, queued.text
        immediate = client.post(
            path,
            json={
                "message": "Change direction now",
                "delivery": "queue" if promote else "interrupt",
                "target_response_id": response.id,
            },
        )
        assert immediate.status_code == 200, immediate.text
        pending_id = immediate.json()["id"]
        if promote:
            promoted = client.post(f"{path}/{pending_id}/interrupt")
            assert promoted.status_code == 200, promoted.text
            assert promoted.json() == {
                **immediate.json(),
                "delivery": "interrupt",
            }
            assert (
                client.post(f"{path}/{pending_id}/interrupt").json() == promoted.json()
            )
        assert cancelled.wait(5)
        if promote:
            additional = client.post(
                path,
                json={
                    "message": "Another instruction",
                    "delivery": "interrupt",
                    "target_response_id": response.id,
                },
            )
            assert additional.status_code == 200, additional.text
        # Cancellation does not release admission until the existing worker exits.
        assert len(requests) == 1
        assert len(client.get(path).json()) == (4 if promote else 3)
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        responses = list(
            db_session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
                .order_by(ChatMessage.id)
            )
        )
        assert responses[0].response_status == RunStatus.CANCELLED
        assert responses[0].message.startswith("Partial answer")
        saved = read_response_record(responses[0], "root")
        assert saved.steps[0].message.text == "Partial answer"
        assert [(row.message, row.response_status) for row in responses[1:]] == [
            ("Done", RunStatus.COMPLETE),
            ("Done", RunStatus.COMPLETE),
            ("Done", RunStatus.COMPLETE),
        ] + ([("Done", RunStatus.COMPLETE)] if promote else [])
        assert list(
            db_session.scalars(
                select(ChatMessage.message)
                .where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.USER,
                )
                .order_by(ChatMessage.id)
            )
        ) == [
            "Initial question",
            "Change direction now",
            # Interrupting messages start before queued ones.
            *(["Another instruction"] if promote else []),
            "Apply this next",
            "Do this later",
        ]
        assert client.get(path).json() == []
        assert client.post(f"{path}/{pending_id}/interrupt").status_code == 409
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_submitted_messages_process_once_and_execute_without_a_browser(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    requests: list[GenerationRequest] = []
    queries: list[str] = []

    def query_hook(
        *,
        payload: dict[str, JsonValue],
        db_session: Session,
        hook_point: HookPoint,
        response_type: type[QueryProcessingResponse],
    ) -> QueryProcessingResponse | HookSkipped:
        del db_session, hook_point, response_type
        query = QueryProcessingPayload.model_validate(payload).query
        queries.append(query)
        if query == "Rejected instruction":
            return QueryProcessingResponse(rejection_message="Instruction rejected")
        if query == "Initial question":
            return HookSkipped()
        return QueryProcessingResponse(query=f"Accepted {query}")

    def generate(
        request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        if len(requests) == 1:
            entered.set()
            assert release.wait(30)
        cancellation.check()
        return AssistantMessage(content=[TextContent(text=f"Answer {len(requests)}")])

    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    monkeypatch.setattr("onyx.chat.process_message.execute_hook", query_hook)
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        response = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert response is not None
        for delivery in MessageDelivery:
            rejected = client.post(
                path,
                json={
                    "message": "Rejected instruction",
                    "delivery": delivery.value,
                    "target_response_id": response.id,
                },
            )
            assert rejected.status_code == 400, rejected.text
            assert rejected.json()["error_code"] == "QUERY_REJECTED"
        assert client.get(path).json() == []
        submitted: list[PendingChatMessage] = []
        for message, delivery in (
            ("Use the latest source", MessageDelivery.SEND),
            ("First queued question", MessageDelivery.QUEUE),
            ("Second queued question", MessageDelivery.QUEUE),
        ):
            result = client.post(
                path,
                json={
                    "message": message,
                    "delivery": delivery.value,
                    "target_response_id": response.id,
                },
            )
            assert result.status_code == 200, result.text
            pending = PendingChatMessage.model_validate(result.json())
            assert pending.message == f"Accepted {message}"
            submitted.append(pending)
        assert list(
            db_session.scalars(
                select(ChatInput.content)
                .where(ChatInput.recipient_session_id == chat.id)
                .order_by(ChatInput.id)
            )
        ) == [row.message for row in submitted]
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        responses = list(
            db_session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
                .order_by(ChatMessage.id)
            )
        )
        assert [(row.message, row.response_status) for row in responses] == [
            ("Answer 2", RunStatus.COMPLETE),
            ("Answer 3", RunStatus.COMPLETE),
            ("Answer 4", RunStatus.COMPLETE),
        ]
        assert [
            [
                (packet.obj.id, packet.obj.message)
                for packet in replay_response(
                    read_response_record(row, "root"), {}, {}, {}
                )
                if isinstance(packet.obj, UserMessagePacket)
            ]
            for row in responses
        ] == [[(submitted[0].id, "Accepted Use the latest source")], [], []]
        assert len(requests) == 4
        assert any(
            isinstance(message, UserMessage)
            and message.text == "Accepted Use the latest source"
            for message in requests[1].messages
        )
        assert all(
            "Rejected instruction" not in message.text
            for request in requests
            for message in request.messages
        )
        assert list(
            db_session.scalars(
                select(ChatMessage.message)
                .where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.USER,
                )
                .order_by(ChatMessage.id)
            )
        ) == [
            "Initial question",
            "Accepted First queued question",
            "Accepted Second queued question",
        ]
        assert queries == [
            "Initial question",
            "Rejected instruction",
            "Rejected instruction",
            "Rejected instruction",
            "Use the latest source",
            "First queued question",
            "Second queued question",
        ]
        assert client.get(path).json() == []
        for pending in submitted:
            assert client.delete(f"{path}/{pending.id}").status_code == 409
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


@pytest.mark.parametrize("ending", ["error", "access_revoked"])
def test_unsuccessful_or_unauthorized_dispatch_preserves_pending_messages(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()

    def generate(
        _request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(30)
        if ending == "error":
            raise RuntimeError("Scripted provider failure")
        return AssistantMessage(content=[TextContent(text="Finished")])

    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        response = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert response is not None
        submitted = client.post(
            path,
            json={
                "message": "Queued question",
                "delivery": "queue",
                "target_response_id": response.id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        pending = PendingChatMessage.model_validate(submitted.json())
        if ending == "access_revoked":
            owner.is_active = False
            db_session.commit()
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        if ending == "access_revoked":
            owner.is_active = True
            db_session.commit()
        assert client.get(path).json() == [pending.model_dump(mode="json")]
        assert list(
            db_session.scalars(
                select(ChatMessage.id).where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
            )
        ) == [response.id]
        withdrawn = client.delete(f"{path}/{pending.id}")
        assert withdrawn.status_code == 200, withdrawn.text
        assert client.get(path).json() == []
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


# Each failure point follows the response reservation in turn preparation.
@pytest.mark.parametrize("failure", ["token_rate_limit", "model_setup", "file_loading"])
def test_queued_start_failure_saves_error_and_pauses_queue(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """A queued message that cannot start is answered with an error, not retried."""
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        if failure == "token_rate_limit":
            raise OnyxError(OnyxErrorCode.RATE_LIMITED, "Usage budget reached")
        raise RuntimeError("Service unavailable")

    monkeypatch.setattr(
        {
            "token_rate_limit": "onyx.chat.process_message.check_token_rate_limits",
            "model_setup": "onyx.chat.process_message.get_llm_for_persona",
            "file_loading": "onyx.chat.process_message.load_chat_files",
        }[failure],
        fail,
    )
    first = client.post(path, json={"message": "First", "delivery": "queue"})
    assert first.status_code == 200, first.text
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    answer = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat.id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    assert answer is not None
    assert answer.response_status == RunStatus.ERROR
    assert answer.response_failure is not None
    assert answer.parent_message is not None
    assert answer.parent_message.message == "First"
    assert client.get(path).json() == []
    # The error pauses the queue, so later queued input waits for the user.
    second = client.post(path, json={"message": "Second", "delivery": "queue"})
    assert second.status_code == 200, second.text
    assert chat_turn_work.wait_idle(timeout=30)
    assert [message["message"] for message in client.get(path).json()] == ["Second"]
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(chat.id, tasks, owner)
    assert not status.has_startable_input
    assert status.latest_response_id == answer.id
    assert tasks.tasks == []


@pytest.mark.parametrize(
    ("targeted", "admission_held"),
    [
        pytest.param(False, False, id="untargeted_idle"),
        pytest.param(True, True, id="targeted_while_releasing"),
    ],
)
def test_late_send_after_a_finished_response_starts_the_next_turn(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    targeted: bool,
    admission_held: bool,
) -> None:
    """A send that misses its response is queued and starts once the chat is idle.

    A held admission is the moment after a stream's stop packet, before its turn
    releases the chat and dispatches queued input.
    """
    chat_id = response.chat_session_id
    path = f"/chat/chat-session/{chat_id}/pending-messages"
    response.response_status = RunStatus.COMPLETE
    db_session.commit()
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(
            content=[TextContent(text="Next answer")]
        )
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    admission = ChatTurnAdmission(get_cache_backend())
    if admission_held:
        admission.claim(chat_id)
    try:
        sent = client.post(
            path,
            json={
                "message": "Next turn",
                "delivery": "send",
                **({"target_response_id": response.id} if targeted else {}),
            },
        )
        assert sent.status_code == 200, sent.text
        pending = PendingChatMessage.model_validate(sent.json())
        assert pending.delivery == MessageDelivery.QUEUE
        assert pending.target_response_id is None
        if admission_held:
            assert chat_turn_work.wait_idle(timeout=30)
            assert client.get(path).json() == [pending.model_dump(mode="json")]
    finally:
        admission.release()
    if admission_held:
        # The finished turn dispatches after it releases the chat.
        dispatch_pending_chat_messages(chat_id, owner.id)
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    question = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == response.id)
    )
    assert question is not None and question.message == "Next turn"
    answer = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == question.id)
    )
    assert answer is not None
    assert answer.response_status == RunStatus.COMPLETE
    assert answer.message == "Next answer"
    assert client.get(path).json() == []


def test_status_recovers_queued_message_after_previous_dispatcher_exits(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    response.response_status = RunStatus.COMPLETE
    db_session.commit()
    with monkeypatch.context() as dispatcher_exits:
        dispatcher_exits.setattr(
            chat_backend, "dispatch_pending_chat_messages", lambda *_: None
        )
        assert (
            client.post(
                path,
                json={
                    "message": "Continue",
                    "delivery": "queue",
                    "target_response_id": response.id,
                },
            ).status_code
            == 200
        )
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(
            content=[TextContent(text="Recovered answer")]
        )
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(
        response.chat_session_id, tasks, owner
    )
    assert not status.is_processing
    assert status.has_startable_input
    asyncio.run(tasks())
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    question = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == response.id)
    )
    assert question is not None and question.message == "Continue"
    answer = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == question.id)
    )
    assert answer is not None and answer.message == "Recovered answer"
    assert client.get(path).json() == []


def test_status_wakes_the_root_for_a_child_whose_owner_is_gone(
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a pod restart, a child stays running without an owner.

    Status reports it, and its dispatch saves the child as failed, so the
    result wakes the root.
    """
    chat_id = response.chat_session_id
    response.response_status = RunStatus.COMPLETE
    child = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        spawned_by_message_id=response.id,
        agent_name="worker",
    )
    db_session.add(child)
    db_session.flush()
    child_response = ChatMessage(
        chat_session_id=child.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.RUNNING,
    )
    db_session.add(child_response)
    db_session.flush()
    db_session.add(
        ChatInput(
            recipient_session_id=chat_id,
            message_id=agent_result_message_id(str(child_response.id)),
            source=InputSource.AGENT_RESULT,
            source_response_id=child_response.id,
            root_response_id=response.id,
            content="",
        )
    )
    db_session.commit()
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(
            content=[TextContent(text="The worker stopped")]
        )
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(chat_id, tasks, owner)
    assert status.has_active_subagents
    assert not status.has_startable_input
    asyncio.run(tasks())
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    stopped = db_session.get(ChatMessage, child_response.id)
    assert stopped is not None and stopped.response_status == RunStatus.ERROR
    follow_up = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.parent_message_id == response.id,
            ChatMessage.message_type == MessageType.AGENT_RESULTS,
        )
    )
    assert follow_up is not None
    answer = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == follow_up.id)
    )
    assert answer is not None and answer.response_status == RunStatus.COMPLETE
    assert answer.message == "The worker stopped"
    status = chat_backend.get_chat_session_processing_status(
        chat_id, BackgroundTasks(), owner
    )
    assert not status.has_active_subagents
    assert status.latest_response_id == answer.id


def test_stop_after_the_answer_finishes_pauses_the_queue(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        entered.set()
        assert release.wait(30)
        # The answer finishes before the turn's control thread reads Stop.
        return AssistantMessage(content=[TextContent(text="Full answer")])

    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    monkeypatch.setattr("onyx.chat.execution._CANCEL_POLL_INTERVAL_S", 30)
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        response = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert response is not None
        queued = client.post(
            path,
            json={
                "message": "Do this later",
                "delivery": "queue",
                "target_response_id": response.id,
            },
        )
        assert queued.status_code == 200, queued.text
        request_stop(chat.id, get_cache_backend(), stream_id=response.id)
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        stopped = db_session.get(ChatMessage, response.id)
        assert stopped is not None
        assert stopped.response_status == RunStatus.CANCELLED
        assert stopped.message == "Full answer"
        # Stop pauses the queue; the queued message waits for the user.
        assert len(requests) == 1
        assert [message["id"] for message in client.get(path).json()] == [
            queued.json()["id"]
        ]
        tasks = BackgroundTasks()
        status = chat_backend.get_chat_session_processing_status(chat.id, tasks, owner)
        assert not status.has_startable_input
        assert tasks.tasks == []
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)
