"""Pending user messages remain editable until Chat accepts them for execution."""

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

from onyx.agents.models import MessageDelivery, RunStatus
from onyx.auth.users import get_anonymous_user
from onyx.cache.factory import get_cache_backend
from onyx.chat.execution import chat_turn_work
from onyx.chat.models import PendingChatMessage
from onyx.chat.presentation import replay_response
from onyx.chat.process_message import handle_stream_message_objects
from onyx.chat.stop_signal_checker import request_stop
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat_inputs import inputs_available, receive_messages
from onyx.db.chat_response import read_response_record
from onyx.db.enums import HookPoint, IncognitoRecordMode
from onyx.db.models import ChatInput, ChatMessage, ChatSession, User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.file_store.models import ChatFileInput, ChatLoadedFile
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


def test_withdraw_returns_editable_text_and_resubmission_joins_queue_tail(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    records: list[PendingChatMessage] = []
    for text in ("First instruction", "Second instruction"):
        submitted = client.post(
            path,
            json={
                "message": text,
                "delivery": "queue",
                "target_response_id": response.id,
            },
        )
        assert submitted.status_code == 200, submitted.text
        records.append(PendingChatMessage.model_validate(submitted.json()))
    withdrawn = client.delete(f"{path}/{records[0].id}")
    assert withdrawn.status_code == 200, withdrawn.text
    assert PendingChatMessage.model_validate(withdrawn.json()) == records[0]
    assert client.delete(f"{path}/{records[0].id}").status_code == 409
    assert (
        db_session.scalar(
            select(ChatInput).where(ChatInput.message_id == records[0].id)
        )
        is None
    )
    resubmitted = client.post(
        path,
        json={
            "message": "Edited instruction",
            "delivery": "queue",
            "target_response_id": response.id,
        },
    )
    assert resubmitted.status_code == 200, resubmitted.text
    replacement = PendingChatMessage.model_validate(resubmitted.json())
    assert replacement.id != records[0].id
    listed = client.get(path)
    assert listed.status_code == 200, listed.text
    assert [PendingChatMessage.model_validate(row) for row in listed.json()] == [
        records[1],
        replacement,
    ]


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
    messages = receive_messages(
        db_session, str(response.chat_session_id), str(response.id), []
    )
    assert len(messages) == 1
    db_session.rollback()
    assert (
        client.post(
            f"{path}/{message_id}/interrupt",
            params={"target_response_id": response.id + 1},
        ).status_code
        == 409
    )
    promoted = client.post(
        f"{path}/{message_id}/interrupt", params={"target_response_id": response.id}
    )
    assert promoted.status_code == 200, promoted.text
    assert not inputs_available(
        db_session, response.id, messages, ownership_version=None
    )
    db_session.rollback()
    assert client.get(path).json() == [promoted.json()]


def test_queue_routes_reject_other_owners(
    client: TestClient,
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    other = make_test_user("pending-chat-other")
    chat = ChatSession(id=uuid4(), user_id=other.id)
    db_session.add(chat)
    db_session.commit()
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    assert client.get(path).status_code == 404
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == 404
    )
    assert client.delete(f"{path}/unknown").status_code == 404
    assert client.post(f"{path}/unknown/interrupt").status_code == 404


@pytest.mark.parametrize(
    "status",
    [None, RunStatus.COMPLETE, RunStatus.CANCELLED, RunStatus.ERROR, RunStatus.LIMIT],
)
def test_send_rejects_responses_without_active_execution(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    status: RunStatus | None,
) -> None:
    response.response_status = status
    db_session.commit()
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    rejected = client.post(
        path,
        json={
            "message": "Late send",
            "delivery": "send",
            "target_response_id": response.id,
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert client.get(path).json() == []


@pytest.mark.parametrize(
    "status", [None, RunStatus.CANCELLED, RunStatus.ERROR, RunStatus.LIMIT]
)
def test_queue_rejects_unknown_responses_and_pauses_after_unsuccessful_execution(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    status: RunStatus | None,
) -> None:
    response.response_status = status
    db_session.commit()
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    submitted = client.post(
        path,
        json={
            "message": "Next turn",
            "delivery": "queue",
            "target_response_id": response.id,
        },
    )
    assert submitted.status_code == (409 if status is None else 200), submitted.text
    assert chat_turn_work.wait_idle(timeout=10)
    assert client.get(path).json() == ([] if status is None else [submitted.json()])
    assert (
        db_session.scalar(
            select(ChatMessage.id).where(ChatMessage.parent_message_id == response.id)
        )
        is None
    )


@pytest.mark.parametrize("is_child", [False, True])
def test_queue_routes_reject_deleted_or_child_sessions(
    client: TestClient,
    owner: User,
    response: ChatMessage,
    db_session: Session,
    is_child: bool,
) -> None:
    chat = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        spawned_by_message_id=response.id if is_child else None,
        deleted=not is_child,
    )
    db_session.add(chat)
    db_session.commit()
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    assert client.get(path).status_code == 404
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == 404
    )
    assert client.delete(f"{path}/unknown").status_code == 404


@pytest.mark.parametrize("mode", list(IncognitoRecordMode))
def test_queue_routes_reject_incognito(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    mode: IncognitoRecordMode,
) -> None:
    response.chat_session.incognito_record_mode = mode
    db_session.commit()
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    assert client.get(path).status_code == 400
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == 400
    )
    assert client.delete(f"{path}/unknown").status_code == 400
    assert client.post(f"{path}/unknown/interrupt").status_code == 400


def test_queue_routes_reject_anonymous_users(
    client: TestClient, app: FastAPI, response: ChatMessage
) -> None:
    for route in app.routes:
        if not isinstance(route, APIRoute) or "pending-messages" not in route.path:
            continue
        for dependency in route.dependant.dependencies:
            if dependency.name == "user":
                assert dependency.call is not None
                app.dependency_overrides[dependency.call] = get_anonymous_user
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    assert client.get(path).status_code == 403
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == 403
    )
    assert client.delete(f"{path}/unknown").status_code == 403
    assert client.post(f"{path}/unknown/interrupt").status_code == 403


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


def test_pending_messages_require_the_selected_response(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    for target in (None, response.parent_message_id):
        rejected = client.post(
            path,
            json={
                "message": "Invalid target",
                "delivery": "queue",
                "target_response_id": target,
            },
        )
        assert rejected.status_code == 400, rejected.text
    queued = client.post(
        path,
        json={
            "message": "Original branch",
            "delivery": "queue",
            "target_response_id": response.id,
        },
    )
    assert queued.status_code == 200, queued.text
    question = response.parent_message
    assert question is not None
    sibling = ChatMessage(
        chat_session_id=response.chat_session_id,
        parent_message_id=question.id,
        message="Preferred",
        token_count=1,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.COMPLETE,
    )
    db_session.add(sibling)
    db_session.flush()
    question.latest_child_message_id = sibling.id
    db_session.commit()
    rejected = client.post(
        path,
        json={
            "message": "Wrong branch",
            "delivery": "queue",
            "target_response_id": response.id,
        },
    )
    assert rejected.status_code == 400, rejected.text
    assert (
        client.post(
            f"{path}/{queued.json()['id']}/interrupt",
            params={"target_response_id": response.id},
        ).status_code
        == 409
    )
    assert client.get(path).json() == [queued.json()]


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
            promoted = client.post(
                f"{path}/{pending_id}/interrupt",
                params={"target_response_id": response.id},
            )
            assert promoted.status_code == 200, promoted.text
            assert promoted.json() == {
                **immediate.json(),
                "delivery": "interrupt",
            }
            assert (
                client.post(
                    f"{path}/{pending_id}/interrupt",
                    params={"target_response_id": response.id},
                ).json()
                == promoted.json()
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
            "Apply this next",
            "Do this later",
        ] + (["Another instruction"] if promote else [])
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


@pytest.mark.parametrize("ending", ["error", "stop", "access_revoked"])
def test_unsuccessful_or_unauthorized_dispatch_preserves_pending_messages(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release, cancelled = Event(), Event(), Event()

    def generate(
        _request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        with cancellation.on_cancel(cancelled.set):
            entered.set()
            assert release.wait(30)
        cancellation.check()
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
        if ending == "stop":
            request_stop(chat.id, get_cache_backend(), stream_id=response.id)
            assert cancelled.wait(5)
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


@pytest.mark.parametrize("preparation_state", ["blocked", "failed"])
def test_withdrawal_dispatches_the_next_message_after_preparation_stops(
    client: TestClient,
    chat: ChatSession,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    preparation_state: str,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )

    def select_model() -> QueueTestLLM:
        if not release.is_set():
            entered.set()
            if preparation_state == "failed":
                raise RuntimeError("Model configuration unavailable")
            assert release.wait(15)
        return model

    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona",
        lambda **_kwargs: select_model(),
    )
    try:
        first = client.post(path, json={"message": "First", "delivery": "queue"})
        assert first.status_code == 200, first.text
        first_pending = PendingChatMessage.model_validate(first.json())
        assert entered.wait(15)
        if preparation_state == "failed":
            assert chat_turn_work.wait_idle(timeout=15)
        second = client.post(path, json={"message": "Second", "delivery": "queue"})
        assert second.status_code == 200, second.text
        if preparation_state == "failed":
            assert chat_turn_work.wait_idle(timeout=15)
            release.set()
        withdrawn = client.delete(f"{path}/{first_pending.id}")
        assert withdrawn.status_code == 200, withdrawn.text
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        assert list(
            db_session.scalars(
                select(ChatMessage.message).where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.USER,
                )
            )
        ) == ["Second"]
        answer = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert answer is not None and answer.response_status == RunStatus.COMPLETE
        assert answer.message == "Done"
        assert client.get(path).json() == []
    finally:
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)


def test_queued_preparation_failure_saves_answer_and_keeps_next_message(
    client: TestClient,
    chat: ChatSession,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail_file_loading(
        _inputs: list[ChatFileInput], *, text_file_ids: set[str] | None = None
    ) -> list[ChatLoadedFile]:
        assert text_file_ids is None
        entered.set()
        assert release.wait(15)
        raise RuntimeError("File store unavailable")

    monkeypatch.setattr("onyx.chat.process_message.load_chat_files", fail_file_loading)
    try:
        first = client.post(path, json={"message": "First", "delivery": "queue"})
        assert first.status_code == 200, first.text
        assert entered.wait(15)
        answer = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert answer is not None
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.refresh(answer)
        assert answer.response_status == RunStatus.ERROR
        assert answer.response_failure is not None
        assert answer.parent_message is not None
        assert answer.parent_message.message == "First"
        assert client.get(path).json() == []
        assert (
            client.post(
                path,
                json={
                    "message": "Second",
                    "delivery": "queue",
                    "target_response_id": answer.id,
                },
            ).status_code
            == 200
        )
        assert len(client.get(path).json()) == 1
    finally:
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)


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
    monkeypatch.setattr(chat_backend, "dispatch_pending_chat_messages", lambda *_: None)
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
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(
        response.chat_session_id, tasks, owner
    )
    assert not status.is_processing
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].args == (response.chat_session_id, owner.id)
