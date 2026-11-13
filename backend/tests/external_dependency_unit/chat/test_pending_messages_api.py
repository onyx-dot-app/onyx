"""Pending user messages remain editable until Chat accepts them for execution."""

import asyncio
import time
from collections.abc import Generator
from concurrent.futures import Future
from threading import Event
from typing import Any, override
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.agents.models import (
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    RunFailure,
    RunFailureKind,
    RunStatus,
    agent_result_message_id,
)
from onyx.cache.factory import get_cache_backend
from onyx.chat import execution
from onyx.chat.chat_processing_checker import ChatTurnAdmission
from onyx.chat.execution import chat_turn_work
from onyx.chat.models import CreateChatSessionID, PendingChatMessage, ResponseOwner
from onyx.chat.presentation import replay_response
from onyx.chat.process_message import (
    dispatch_pending_chat_messages,
    handle_multi_model_stream,
    handle_stream_message_objects,
    run_chat_turn,
)
from onyx.chat.run_store import RESPONSE_OWNER_KEY_PREFIX
from onyx.chat.stop_signal_checker import request_stop
from onyx.chat.stream_buffer import StreamBufferWriter
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.context.search.models import BaseFilters
from onyx.db.chat import delete_chat_session, reserve_chat_response_ids
from onyx.db.chat_inputs import (
    MAX_PENDING_MESSAGE_BYTES,
    consume_inputs__no_commit,
    list_human_messages,
    pause_chat_queue__no_commit,
    read_chat_inbox,
    read_run_inputs,
    submit_human_message__no_commit,
    withdraw_human_message__no_commit,
)
from onyx.db.chat_response import read_response_record
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint, IncognitoRecordMode
from onyx.db.models import ChatInput, ChatMessage, ChatSession, ToolCall, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.hooks.executor import HookSkipped
from onyx.hooks.points.query_processing import (
    QueryProcessingPayload,
    QueryProcessingResponse,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, GenerationContext, LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    GenerationStartEvent,
    TextContent,
    TextDeltaEvent,
    ToolResultMessage,
    UserMessage,
    content_text,
)
from onyx.llm.models import ToolCall as ModelToolCall
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat import chat_backend
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
    MessageResponseIDInfo,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    CodeModeStart,
    StreamingError,
    UserMessagePacket,
)
from onyx.tools.constants import SPAWN_AGENT_TOOL_NAME
from onyx.tools.models import ChatToolSelection
from onyx.tools.tool_implementations.code_mode.store import ProgramStore
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.unit.onyx.agents.fakes import FakeModelClient

# A status request without pass-through headers.
_NO_HEADERS = Request({"type": "http", "headers": []})


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
def response(
    db_session: Session, chat: ChatSession
) -> Generator[ChatMessage, None, None]:
    """A running response whose owner is live, so dispatch does not repair it."""
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
    cache = get_cache_backend()
    owner_key = f"{RESPONSE_OWNER_KEY_PREFIX}{answer.id}"
    cache.set(
        owner_key,
        ResponseOwner(token=uuid4(), root_message_id=answer.id)
        .model_dump_json()
        .encode(),
        ex=600,
    )
    yield answer
    cache.delete(owner_key)


@pytest.fixture
def app(db_session: Session, owner: User) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_backend.router)
    register_onyx_exception_handlers(app)
    for route in app.routes:
        if not isinstance(route, APIRoute) or not (
            "pending-messages" in route.path or "stop-subagents" in route.path
        ):
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


@pytest.mark.parametrize("change", ["withdraw", "interrupt"])
def test_input_changed_after_a_run_read_it_is_not_accepted(
    client: TestClient, response: ChatMessage, db_session: Session, change: str
) -> None:
    """Withdrawal and promotion win over a step that already read the input.

    Accepted input cannot be withdrawn, and a second step finds nothing left.
    """
    chat_id = response.chat_session_id

    def read() -> list[UserMessage]:
        messages = read_run_inputs(
            db_session, str(chat_id), str(response.id), [response.id], None
        )[0]
        assert len(messages) == 1
        assert messages[0].metadata == InputMessageMetadata(source=InputSource.HUMAN)
        return messages

    accepted = submit_human_message__no_commit(
        db_session,
        chat_id,
        message="Focus on cost",
        delivery=MessageDelivery.SEND,
        target_response_id=response.id,
        turn_preparing=False,
    )
    messages = read()
    assert consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    db_session.commit()
    with pytest.raises(OnyxError) as withdrawn:
        withdraw_human_message__no_commit(db_session, chat_id, accepted.id)
    assert withdrawn.value.error_code == OnyxErrorCode.CONFLICT
    assert not consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    db_session.rollback()

    path = f"/chat/chat-session/{chat_id}/pending-messages"
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
    messages = read()
    db_session.rollback()
    if change == "withdraw":
        assert client.delete(f"{path}/{message_id}").status_code == 200
        remaining = []
    else:
        promoted = client.post(f"{path}/{message_id}/interrupt")
        assert promoted.status_code == 200, promoted.text
        remaining = [promoted.json()]
    assert not consume_inputs__no_commit(
        db_session, response.id, messages, [], ownership_version=None
    )
    db_session.rollback()
    assert client.get(path).json() == remaining


@pytest.mark.parametrize(
    ("status", "stopped"),
    [(RunStatus.COMPLETE, True), (RunStatus.CANCELLED, True), (RunStatus.ERROR, False)],
)
def test_late_send_is_queued_and_waits_after_a_stop_or_failure(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    status: RunStatus,
    stopped: bool,
) -> None:
    response.response_status = status
    if stopped:
        pause_chat_queue__no_commit(db_session, response.chat_session_id)
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


def test_queue_routes_reject_a_child_session(
    client: TestClient, owner: User, response: ChatMessage, db_session: Session
) -> None:
    """A child agent's session has no human queue."""
    child = ChatSession(id=uuid4(), user_id=owner.id, spawned_by_message_id=response.id)
    db_session.add(child)
    db_session.commit()
    path = f"/chat/chat-session/{child.id}/pending-messages"
    assert client.get(path).status_code == 404
    assert (
        client.post(path, json={"message": "Private", "delivery": "queue"}).status_code
        == 404
    )
    assert client.delete(f"{path}/unknown").status_code == 404
    assert client.post(f"{path}/unknown/interrupt").status_code == 404


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


def test_interrupt_rejects_a_finished_response_on_another_branch(
    client: TestClient, response: ChatMessage, db_session: Session
) -> None:
    question = response.parent_message
    assert question is not None
    response.response_status = RunStatus.COMPLETE
    selected = ChatMessage(
        chat_session_id=response.chat_session_id,
        parent_message_id=question.id,
        message="Regenerated",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.COMPLETE,
    )
    db_session.add(selected)
    db_session.flush()
    question.latest_child_message_id = selected.id
    db_session.commit()
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    # The earlier answer is no longer on the selected branch.
    stale = client.post(
        path,
        json={
            "message": "Change direction",
            "delivery": "interrupt",
            "target_response_id": response.id,
        },
    )
    assert stale.status_code == 409, stale.text
    assert client.get(path).json() == []
    current = client.post(
        path,
        json={
            "message": "Change direction",
            "delivery": "queue",
            "target_response_id": selected.id,
        },
    )
    assert current.status_code == 200, current.text


def test_an_incognito_chat_saves_its_tool_selection(
    chat: ChatSession, owner: User, db_session: Session
) -> None:
    chat.incognito_record_mode = IncognitoRecordMode.FULL_HISTORY
    db_session.commit()
    selection = ChatToolSelection(allowed_tool_ids=[1], preferred_tool_id=None)
    assert (
        chat_backend.update_chat_tool_selection(chat.id, selection, owner, db_session)
        == selection
    )
    db_session.expire_all()
    saved = db_session.get(ChatSession, chat.id)
    assert saved is not None
    assert saved.tool_selection == selection


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


@pytest.mark.parametrize("code_mode", [False, True])
def test_submitted_messages_process_once_and_execute_without_a_browser(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    code_mode: bool,
) -> None:
    """A send reaches the response at its next step boundary.

    With code mode, the send arrives while a program runs and the step waits
    on it with `wait_code`; the program finishes before the next step reads it.
    """
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release, waiting = Event(), Event(), Event()
    requests: list[GenerationRequest] = []
    # Steps of the first response before the one that reads the send.
    steps = 2 if code_mode else 1
    monkeypatch.setattr("onyx.chat.agent.CODE_MODE_ENABLED", code_mode)
    store = ProgramStore.store

    def gated_store(program_store: ProgramStore, key: object, value: object) -> None:
        if key == "gate":
            assert waiting.wait(30)
            entered.set()
            assert release.wait(30)
        store(program_store, key, value)

    monkeypatch.setattr(ProgramStore, "store", gated_store)
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
        if code_mode and len(requests) == 1:
            program = "print('started')\nyield_control()\nstore('gate', 1)\n"
            return AssistantMessage(
                content=[
                    ModelToolCall(
                        id="start", name="execute_code", arguments={"code": program}
                    )
                ]
            )
        if code_mode and len(requests) == 2:
            waiting.set()
            return AssistantMessage(
                content=[
                    ModelToolCall(
                        id="wait",
                        name="wait_code",
                        arguments={"cell_id": 1, "yield_time_ms": 30000},
                    )
                ]
            )
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
            (f"Answer {steps + 1}", RunStatus.COMPLETE),
            (f"Answer {steps + 2}", RunStatus.COMPLETE),
            (f"Answer {steps + 3}", RunStatus.COMPLETE),
        ]
        replayed = [
            list(replay_response(read_response_record(row, "root"), {}, {}, {}))
            for row in responses
        ]
        assert [
            [
                (packet.obj.id, packet.obj.message)
                for packet in packets
                if isinstance(packet.obj, UserMessagePacket)
            ]
            for packets in replayed
        ] == [[(submitted[0].id, "Accepted Use the latest source")], [], []]
        # The step that read the send saves it; earlier steps saved none.
        assert [
            [accepted.content for accepted in item.inputs]
            for item in sorted(
                responses[0].response_items, key=lambda item: item.step_index
            )
        ] == [[]] * steps + [["Accepted Use the latest source"]]
        assert len(requests) == steps + 3
        # The live step and the next turn's saved history both read the send
        # after everything the steps before it produced.
        for request in (requests[steps], requests[steps + 1]):
            texts = [
                message.text if isinstance(message, UserMessage) else None
                for message in request.messages
            ]
            sent = texts.index("Accepted Use the latest source")
            before = request.messages[sent - 1]
            if code_mode:
                assert isinstance(before, ToolResultMessage)
                assert before.tool_call_id == "wait"
                assert "Execution completed in cell 1" in content_text(before.content)
            else:
                assert isinstance(before, AssistantMessage)
        if code_mode:
            # Replay shows the send after the program and before the answer.
            positions = [
                type(packet.obj).__name__
                for packet in replayed[0]
                if isinstance(packet.obj, (CodeModeStart, UserMessagePacket))
            ]
            assert positions == ["CodeModeStart", "CodeModeStart", "UserMessagePacket"]
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


def test_send_now_starts_after_a_send_fails_during_preparation(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send that fails after saving its question leaves a startable queue."""
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("File store unavailable")

    with monkeypatch.context() as failing_files:
        failing_files.setattr("onyx.chat.process_message.load_chat_files", fail)
        packets = list(
            handle_stream_message_objects(
                new_msg_req=SendMessageRequest(
                    message="Initial question", chat_session_id=chat.id
                ),
                user=owner,
            )
        )
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    [failed] = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat.id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    ).all()
    assert failed.response_status == RunStatus.ERROR
    # The client learns the saved turn's IDs before its error.
    ids, error = packets
    assert ids == MessageResponseIDInfo(
        user_message_id=failed.parent_message_id,
        reserved_assistant_message_id=failed.id,
    )
    assert isinstance(error, StreamingError)

    sent_now = client.post(path, json={"message": "Try again", "delivery": "interrupt"})
    assert sent_now.status_code == 200, sent_now.text
    assert chat_turn_work.wait_idle(timeout=30)
    assert client.get(path).json() == []
    db_session.expire_all()
    questions = db_session.scalars(
        select(ChatMessage.message).where(
            ChatMessage.chat_session_id == chat.id,
            ChatMessage.message_type == MessageType.USER,
        )
    ).all()
    assert sorted(questions) == ["Initial question", "Try again"]


def test_a_send_that_creates_its_session_names_it_when_preparation_fails(
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("File store unavailable")

    monkeypatch.setattr("onyx.chat.process_message.load_chat_files", fail)
    packets = list(
        handle_stream_message_objects(
            new_msg_req=SendMessageRequest(
                message="Question", chat_session_info=ChatSessionCreationRequest()
            ),
            user=owner,
        )
    )
    assert chat_turn_work.wait_idle(timeout=30)
    created = packets[0]
    assert isinstance(created, CreateChatSessionID) and not created.incognito
    try:
        _, ids, error = packets
        assert isinstance(ids, MessageResponseIDInfo)
        assert isinstance(error, StreamingError)
        saved = db_session.get(ChatMessage, ids.reserved_assistant_message_id)
        assert saved is not None
        assert saved.chat_session_id == created.chat_session_id
        assert saved.response_status == RunStatus.ERROR
    finally:
        delete_chat_session(
            owner.id, created.chat_session_id, db_session, hard_delete=True
        )


@pytest.mark.parametrize("failure", ["preparation", "start"])
def test_a_failure_before_the_stream_names_only_a_turn_with_saved_content(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """A content-free question has no saved text, so its failure has no IDs."""
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Unavailable")

    if failure == "preparation":
        chat.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
        db_session.commit()
        monkeypatch.setattr("onyx.chat.process_message.load_chat_files", fail)
    else:
        monkeypatch.setattr("onyx.chat.process_message.start_chat_turn", fail)
    packets = list(
        handle_stream_message_objects(
            new_msg_req=SendMessageRequest(message="Question", chat_session_id=chat.id),
            user=owner,
        )
    )
    assert chat_turn_work.wait_idle(timeout=30)
    assert isinstance(packets[-1], StreamingError)
    assert [type(packet) for packet in packets[:-1]] == (
        [] if failure == "preparation" else [MessageResponseIDInfo]
    )


def test_a_non_streaming_send_that_fails_after_saving_raises_its_error(
    chat: ChatSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("File store unavailable")

    monkeypatch.setattr("onyx.chat.process_message.load_chat_files", fail)
    with pytest.raises(OnyxError):
        run_chat_turn(
            new_msg_req=SendMessageRequest(message="Question", chat_session_id=chat.id),
            user=owner,
        )
    assert chat_turn_work.wait_idle(timeout=30)


def test_a_send_after_a_failed_turn_continues_the_conversation(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A send whose parent is a failed response keeps the failed turn in history.

    The model sees the question and the partial output, and the first step
    reads an agent result that the failed turn left unread.
    """
    requests: list[GenerationRequest] = []

    class FailingFirstModel(QueueTestLLM):
        @override
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            requests.append(request)
            if len(requests) == 1:
                yield GenerationStartEvent()
                yield TextDeltaEvent(content_index=0, text="Partial answer")
                raise RuntimeError("Provider failed")
            yield from super().stream(request, context)

    model = FailingFirstModel(
        lambda _request, _signal: AssistantMessage(
            content=[TextContent(text="Recovered answer")]
        )
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    for _packet in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Original question", chat_session_id=chat.id
        ),
        user=owner,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    [failed] = db_session.scalars(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat.id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    ).all()
    assert failed.response_status == RunStatus.ERROR
    worker = ChatSession(
        id=uuid4(),
        user_id=owner.id,
        persona_id=DEFAULT_PERSONA_ID,
        spawned_by_message_id=failed.id,
        agent_name="worker",
    )
    db_session.add(worker)
    db_session.flush()
    worker_response = ChatMessage(
        chat_session_id=worker.id,
        message="",
        token_count=0,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.ERROR,
        response_failure=RunFailure(
            kind=RunFailureKind.EXECUTION, message="Worker stopped early"
        ),
    )
    db_session.add(worker_response)
    db_session.flush()
    result_id = agent_result_message_id(str(worker_response.id))
    db_session.add(
        ChatInput(
            recipient_session_id=chat.id,
            message_id=result_id,
            source=InputSource.AGENT_RESULT,
            source_response_id=worker_response.id,
            root_response_id=failed.id,
            content="",
        )
    )
    db_session.commit()

    for _packet in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Try again",
            chat_session_id=chat.id,
            parent_message_id=failed.id,
        ),
        user=owner,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)

    assert len(requests) == 2
    history = [
        (type(message).__name__, message.text)
        for message in requests[1].messages
        if isinstance(message, UserMessage | AssistantMessage)
    ]
    assert history[:3] == [
        ("UserMessage", "Original question"),
        ("AssistantMessage", "Partial answer"),
        ("UserMessage", "Try again"),
    ]
    [(kind, result_text)] = history[3:]
    assert kind == "UserMessage"
    assert result_text.startswith("Background agent result")
    assert "Worker stopped early" in result_text
    db_session.expire_all()
    question = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == failed.id)
    )
    assert question is not None and question.message == "Try again"
    answer = db_session.scalar(
        select(ChatMessage).where(ChatMessage.parent_message_id == question.id)
    )
    assert answer is not None and answer.response_status == RunStatus.COMPLETE
    assert (
        db_session.scalar(select(ChatInput.id).where(ChatInput.message_id == result_id))
        is None
    )


# Each failure point follows the response reservation in turn preparation.
@pytest.mark.parametrize(
    ("work", "failure"),
    [
        ("message", "token_rate_limit"),
        ("message", "write_access"),
        ("message", "model_setup"),
        ("message", "file_loading"),
        ("results", "token_rate_limit"),
    ],
)
def test_queued_start_failure_saves_error_and_pauses_queue(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    work: str,
    failure: str,
) -> None:
    """Queued work that cannot start is answered with an error, not retried.

    The work is a queued message, or a follow-up on a child's result.
    """
    chat_id = response.chat_session_id
    response.response_status = RunStatus.COMPLETE
    if work == "results":
        child = ChatSession(
            id=uuid4(), user_id=owner.id, spawned_by_message_id=response.id
        )
        db_session.add(child)
        db_session.flush()
        finished = ChatMessage(
            chat_session_id=child.id,
            message="",
            token_count=0,
            message_type=MessageType.ASSISTANT,
            response_status=RunStatus.COMPLETE,
        )
        db_session.add(finished)
        db_session.flush()
        db_session.add(
            ChatInput(
                recipient_session_id=chat_id,
                message_id=agent_result_message_id(str(finished.id)),
                source=InputSource.AGENT_RESULT,
                source_response_id=finished.id,
                root_response_id=response.id,
                content="",
            )
        )
    db_session.commit()
    path = f"/chat/chat-session/{chat_id}/pending-messages"
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

    if failure == "write_access":
        # Write access can end while the message waits; read access remains.
        monkeypatch.setattr(
            "onyx.chat.process_message.has_global_permission",
            lambda _user, _permission: False,
        )
    else:
        monkeypatch.setattr(
            {
                "token_rate_limit": "onyx.chat.process_message.check_token_rate_limits",
                "model_setup": "onyx.chat.process_message.get_llm_for_persona",
                "file_loading": "onyx.chat.process_message.load_chat_files",
            }[failure],
            fail,
        )
    if work == "message":
        first = client.post(path, json={"message": "First", "delivery": "queue"})
        assert first.status_code == 200, first.text
    else:
        dispatch_pending_chat_messages(chat_id, owner.id)
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    answer = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.id != response.id,
        )
    )
    assert answer is not None
    assert answer.response_status == RunStatus.ERROR
    assert answer.response_failure is not None
    assert answer.response_items == []
    question = answer.parent_message
    assert question is not None and question.parent_message_id == response.id
    if work == "message":
        assert question.message_type == MessageType.USER
        assert question.message == "First"
    else:
        assert question.message_type == MessageType.AGENT_RESULTS
        assert question.message == ""
    assert client.get(path).json() == []
    # The error pauses the queue, so later queued input waits for the user.
    second = client.post(path, json={"message": "Second", "delivery": "queue"})
    assert second.status_code == 200, second.text
    assert chat_turn_work.wait_idle(timeout=30)
    assert [message["message"] for message in client.get(path).json()] == ["Second"]
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(
        chat_id, tasks, _NO_HEADERS, owner
    )
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
        # The finished turn published its stream before it releases the chat.
        admission.publish(1)
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


def test_a_send_right_after_the_stream_ends_is_admitted(
    chat: ChatSession, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that reads the stream to its end can send again at once."""
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Hi")])
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    # Hold the last replay write, which runs after the reader sees the end.
    replay_done = Event()
    mark_done = StreamBufferWriter.mark_done

    def held_mark_done(writer: StreamBufferWriter) -> None:
        replay_done.wait(10)
        mark_done(writer)

    monkeypatch.setattr(StreamBufferWriter, "mark_done", held_mark_done)
    try:
        for message in ("First", "Second"):
            errors = [
                packet
                for packet in handle_stream_message_objects(
                    new_msg_req=SendMessageRequest(
                        message=message, chat_session_id=chat.id
                    ),
                    user=owner,
                )
                if isinstance(packet, StreamingError)
            ]
            assert errors == [], message
    finally:
        replay_done.set()
    assert chat_turn_work.wait_idle(timeout=30)


def test_send_during_preparation_goes_to_the_preparing_turn(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
) -> None:
    """A send before the preparing turn reserves its response is read by that response."""
    chat_id = response.chat_session_id
    path = f"/chat/chat-session/{chat_id}/pending-messages"
    response.response_status = RunStatus.COMPLETE
    question = ChatMessage(
        chat_session_id=chat_id,
        parent_message_id=response.id,
        message="Next question",
        token_count=2,
        message_type=MessageType.USER,
    )
    db_session.add(question)
    db_session.commit()
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(chat_id)
    try:
        sent = client.post(
            path,
            json={
                "message": "Focus on cost",
                "delivery": "send",
                "target_response_id": response.id,
            },
        )
        assert sent.status_code == 200, sent.text
        pending = PendingChatMessage.model_validate(sent.json())
        assert pending.delivery == MessageDelivery.SEND
        assert pending.target_response_id is None
        [reserved] = reserve_chat_response_ids(
            db_session, chat_id, question.id, ["Model"]
        )
        assert [
            message.content
            for message in read_run_inputs(
                db_session, str(chat_id), str(reserved), [reserved], None
            )[0]
        ] == ["Focus on cost"]
    finally:
        admission.release()


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
    model_headers: list[dict[str, str] | None] = []

    def model_for_persona(**kwargs: Any) -> QueueTestLLM:
        model_headers.append(kwargs["additional_headers"])
        return model

    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", model_for_persona
    )
    monkeypatch.setattr(chat_backend, "LITELLM_PASS_THROUGH_HEADERS", ["x-proxy-user"])
    tasks = BackgroundTasks()
    # The status poll that recovers the queue passes on its own request's headers.
    status = chat_backend.get_chat_session_processing_status(
        response.chat_session_id,
        tasks,
        Request({"type": "http", "headers": [(b"x-proxy-user", b"user-1")]}),
        owner,
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
    assert model_headers == [{"x-proxy-user": "user-1"}]
    assert client.get(path).json() == []


@pytest.mark.parametrize("lost_status", [RunStatus.RUNNING, RunStatus.SUSPENDED])
def test_status_wakes_the_root_for_a_child_whose_owner_is_gone(
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    lost_status: RunStatus,
) -> None:
    """After a pod restart, a running or suspended child has no owner.

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
        response_status=lost_status,
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
    status = chat_backend.get_chat_session_processing_status(
        chat_id, tasks, _NO_HEADERS, owner
    )
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
        chat_id, BackgroundTasks(), _NO_HEADERS, owner
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
        # The finished answer keeps its status; Stop pauses the queue instead.
        assert stopped.response_status == RunStatus.COMPLETE
        assert stopped.message == "Full answer"
        db_session.refresh(chat)
        assert chat.queue_paused_at is not None
        # Stop pauses the queue; the queued message waits for the user.
        assert len(requests) == 1
        assert [message["id"] for message in client.get(path).json()] == [
            queued.json()["id"]
        ]
        tasks = BackgroundTasks()
        status = chat_backend.get_chat_session_processing_status(
            chat.id, tasks, _NO_HEADERS, owner
        )
        assert not status.has_startable_input
        assert tasks.tasks == []
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_stop_after_the_last_stop_check_pauses_the_queue(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Stop that arrives after the finished turn reads Stop still pauses the queue."""
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        entered.set()
        assert release.wait(30)
        return AssistantMessage(content=[TextContent(text="Full answer")])

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
        queued = client.post(
            path, json={"message": "Do this later", "delivery": "queue"}
        )
        assert queued.status_code == 200, queued.text

        def stop() -> None:
            with Session(db_session.get_bind()) as session:
                chat_backend.stop_chat_session(chat.id, None, owner, session)

        stops: list[Future[None]] = []
        read_stop = execution.is_stop_requested

        def stop_after_the_check(*args: Any, **kwargs: Any) -> bool:
            requested = read_stop(*args, **kwargs)
            if not stops:
                # The user presses Stop right after the turn's last Stop check.
                stops.append(start_thread_future(stop, name="late-stop"))
            return requested

        claim = ChatTurnAdmission.claim

        def claim_after_stop(admission: ChatTurnAdmission, session_id: UUID) -> None:
            # The queued turn claims the chat only after Stop was recorded.
            if stops:
                stops[0].result(timeout=30)
            claim(admission, session_id)

        monkeypatch.setattr(execution, "is_stop_requested", stop_after_the_check)
        monkeypatch.setattr(ChatTurnAdmission, "claim", claim_after_stop)
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        assert stops
        stops[0].result(timeout=30)
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        finished = db_session.scalar(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
        )
        assert finished is not None
        assert finished.response_status == RunStatus.COMPLETE
        db_session.refresh(chat)
        assert chat.queue_paused_at is not None
        assert len(requests) == 1
        assert [message["id"] for message in client.get(path).json()] == [
            queued.json()["id"]
        ]
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_interrupt_does_not_stop_the_turn_it_starts(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn that ends before the interrupt's Stop lets the interrupt run to completion."""
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release, interrupt_started, finish_interrupt = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        if len(requests) == 1:
            entered.set()
            assert release.wait(30)
            return AssistantMessage(content=[TextContent(text="First answer")])
        interrupt_started.set()
        assert finish_interrupt.wait(30)
        return AssistantMessage(content=[TextContent(text="Interrupt answer")])

    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    stop_turn = chat_backend.stop_current_turn

    def stop_after_the_interrupt_starts(*args: Any, **kwargs: Any) -> None:
        # The first turn finishes and starts the interrupt before its Stop runs.
        release.set()
        assert interrupt_started.wait(30)
        stop_turn(*args, **kwargs)
        finish_interrupt.set()

    monkeypatch.setattr(
        chat_backend, "stop_current_turn", stop_after_the_interrupt_starts
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
        interrupted = client.post(
            path, json={"message": "Change direction", "delivery": "interrupt"}
        )
        assert interrupted.status_code == 200, interrupted.text
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        answers = db_session.scalars(
            select(ChatMessage)
            .where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
            .order_by(ChatMessage.id)
        ).all()
        assert [(answer.message, answer.response_status) for answer in answers] == [
            ("First answer", RunStatus.COMPLETE),
            ("Interrupt answer", RunStatus.COMPLETE),
        ]
    finally:
        release.set()
        finish_interrupt.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_queued_turn_keeps_the_pass_through_headers_of_the_turn_before_it(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        if len(requests) == 1:
            entered.set()
            assert release.wait(30)
        return AssistantMessage(content=[TextContent(text="Answer")])

    model = QueueTestLLM(generate)
    model_headers: list[dict[str, str] | None] = []

    def model_for_persona(**kwargs: Any) -> QueueTestLLM:
        model_headers.append(kwargs["additional_headers"])
        return model

    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", model_for_persona
    )
    headers = {"x-proxy-user": "user-1"}
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
        litellm_additional_headers=headers,
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        queued = client.post(path, json={"message": "Follow up", "delivery": "queue"})
        assert queued.status_code == 200, queued.text
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        assert len(requests) == 2
        assert model_headers == [headers, headers]
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_status_repairs_a_running_root_whose_owner_is_gone(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued message behind a crashed root response is not stuck."""
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    with monkeypatch.context() as dispatcher_exits:
        dispatcher_exits.setattr(
            chat_backend, "dispatch_pending_chat_messages", lambda *_: None
        )
        queued = client.post(
            path,
            json={
                "message": "Continue",
                "delivery": "queue",
                "target_response_id": response.id,
            },
        )
        assert queued.status_code == 200, queued.text
    get_cache_backend().delete(f"{RESPONSE_OWNER_KEY_PREFIX}{response.id}")
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(
        response.chat_session_id, tasks, _NO_HEADERS, owner
    )
    assert not status.is_processing
    assert not status.has_startable_input
    assert tasks.tasks
    asyncio.run(tasks())
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    repaired = db_session.get(ChatMessage, response.id)
    assert repaired is not None
    assert repaired.response_status == RunStatus.ERROR
    # An error pauses the queue until the user resumes it.
    assert [message["id"] for message in client.get(path).json()] == [
        queued.json()["id"]
    ]


@pytest.mark.parametrize("status", [RunStatus.COMPLETE, RunStatus.LIMIT])
def test_idle_stop_pauses_the_queue_and_keeps_the_answer(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
) -> None:
    chat_id = response.chat_session_id
    response.response_status = status
    db_session.commit()
    monkeypatch.setattr(chat_backend, "dispatch_pending_chat_messages", lambda *_: None)
    # With nothing queued, Stop still pauses the queue the next message joins.
    chat_backend.stop_chat_session(chat_id, None, owner, db_session)
    queued = client.post(
        f"/chat/chat-session/{chat_id}/pending-messages",
        json={"message": "Do this later", "delivery": "queue"},
    )
    assert queued.status_code == 200, queued.text
    db_session.expire_all()
    stopped = db_session.get(ChatMessage, response.id)
    assert stopped is not None
    assert stopped.response_status == status
    assert not chat_backend.get_chat_session_processing_status(
        chat_id, BackgroundTasks(), _NO_HEADERS, owner
    ).has_startable_input

    # A new turn resumes the queue.
    reserve_chat_response_ids(db_session, chat_id, response.id, ["Model"])
    db_session.commit()
    paused_chat = db_session.get(ChatSession, chat_id)
    assert paused_chat is not None
    assert paused_chat.queue_paused_at is None


def test_stop_of_a_multi_model_turn_pauses_the_queue(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Stop that reaches a multi-model turn after both answers finish keeps them."""
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    entered, release = Event(), Event()
    requests: list[GenerationRequest] = []

    def generate(
        request: GenerationRequest, _cancellation: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        if len(requests) == 2:
            entered.set()
        assert release.wait(30)
        return AssistantMessage(content=[TextContent(text="Full answer")])

    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    # The answers finish before the turn's control thread reads Stop.
    monkeypatch.setattr("onyx.chat.execution._CANCEL_POLL_INTERVAL_S", 30)
    stream = handle_multi_model_stream(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
        llm_overrides=[
            LLMOverride(model_provider="openai", model_version="first"),
            LLMOverride(model_provider="openai", model_version="second"),
        ],
    )
    assert isinstance(stream, Generator)
    try:
        next(stream)
        stream.close()
        assert entered.wait(15)
        queued = client.post(
            path, json={"message": "Do this later", "delivery": "queue"}
        )
        assert queued.status_code == 200, queued.text
        chat_backend.stop_chat_session(chat.id, None, owner, db_session)
        release.set()
        assert chat_turn_work.wait_idle(timeout=30)
        db_session.expire_all()
        responses = list(
            db_session.scalars(
                select(ChatMessage).where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.ASSISTANT,
                )
            )
        )
        assert [row.response_status for row in responses] == [
            RunStatus.COMPLETE,
            RunStatus.COMPLETE,
        ]
        assert len(requests) == 2
        assert [message["id"] for message in client.get(path).json()] == [
            queued.json()["id"]
        ]
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_stop_while_a_turn_holds_admission_without_a_stream_pauses_the_queue(
    client: TestClient,
    response: ChatMessage,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn that has no stream, such as one still preparing, does not lose a Stop."""
    chat_id = response.chat_session_id
    response.response_status = RunStatus.COMPLETE
    db_session.commit()
    monkeypatch.setattr(chat_backend, "dispatch_pending_chat_messages", lambda *_: None)
    queued = client.post(
        f"/chat/chat-session/{chat_id}/pending-messages",
        json={"message": "Do this later", "delivery": "queue"},
    )
    assert queued.status_code == 200, queued.text
    admission = ChatTurnAdmission(get_cache_backend())
    admission.claim(chat_id)
    try:
        chat_backend.stop_chat_session(chat_id, None, owner, db_session)
    finally:
        admission.release()
    assert not chat_backend.get_chat_session_processing_status(
        chat_id, BackgroundTasks(), _NO_HEADERS, owner
    ).has_startable_input


def test_pending_message_over_the_byte_limit_is_rejected(
    client: TestClient, response: ChatMessage
) -> None:
    path = f"/chat/chat-session/{response.chat_session_id}/pending-messages"
    # Each character takes two bytes, so the text is under the limit in characters.
    message = "é" * (MAX_PENDING_MESSAGE_BYTES // 2 + 1)
    rejected = client.post(path, json={"message": message, "delivery": "queue"})
    assert rejected.status_code == 413, rejected.text
    assert client.get(path).json() == []


def test_interrupt_during_preparation_stops_the_turn_when_it_publishes(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/chat/chat-session/{chat.id}/pending-messages"
    preparing, release = Event(), Event()

    class StoppableModel(QueueTestLLM):
        @override
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            # The first answer runs until the interrupt's Stop reaches its stream.
            assert context is not None and context.cancellation is not None
            stopped = Event()
            yield GenerationStartEvent()
            with context.cancellation.on_cancel(stopped.set):
                assert stopped.wait(30)
            context.cancellation.check()

    def answer(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        return AssistantMessage(content=[TextContent(text="Done")])

    first_model, model = StoppableModel(answer), QueueTestLLM(answer)
    calls: list[None] = []

    def prepare_model(**_kwargs: object) -> QueueTestLLM:
        calls.append(None)
        if len(calls) == 1:
            preparing.set()
            assert release.wait(30)
            return first_model
        return model

    monkeypatch.setattr("onyx.chat.process_message.get_llm_for_persona", prepare_model)
    stream = handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message="Initial question", chat_session_id=chat.id
        ),
        user=owner,
    )
    assert isinstance(stream, Generator)
    started = start_thread_future(lambda: next(stream), name="test-first-turn")
    try:
        assert preparing.wait(15)
        interrupt = client.post(
            path, json={"message": "Change direction now", "delivery": "interrupt"}
        )
        assert interrupt.status_code == 200, interrupt.text
        release.set()
        started.result(timeout=30)
        stream.close()
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
        assert [row.response_status for row in responses] == [
            RunStatus.CANCELLED,
            RunStatus.COMPLETE,
        ]
        assert list(
            db_session.scalars(
                select(ChatMessage.message)
                .where(
                    ChatMessage.chat_session_id == chat.id,
                    ChatMessage.message_type == MessageType.USER,
                )
                .order_by(ChatMessage.id)
            )
        ) == ["Initial question", "Change direction now"]
        assert client.get(path).json() == []
    finally:
        release.set()
        stream.close()
        assert chat_turn_work.wait_idle(timeout=30)


def test_a_queued_message_starts_its_turn_as_deep_research(
    client: TestClient, chat: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[SendMessageRequest] = []

    def prepare(*, new_msg_req: SendMessageRequest, **_kwargs: Any) -> None:
        started.append(new_msg_req)
        raise OnyxError(OnyxErrorCode.CONFLICT, "Recorded the queued turn")

    monkeypatch.setattr("onyx.chat.process_message.prepare_chat_turn", prepare)
    queued = client.post(
        f"/chat/chat-session/{chat.id}/pending-messages",
        json={"message": "Research this", "delivery": "queue", "deep_research": True},
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["deep_research"] is True
    assert chat_turn_work.wait_idle(timeout=30)
    assert [request.deep_research for request in started] == [True]


def test_a_queued_message_starts_its_turn_with_the_model_it_was_sent_with(
    client: TestClient, chat: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[SendMessageRequest] = []

    def prepare(*, new_msg_req: SendMessageRequest, **_kwargs: Any) -> None:
        started.append(new_msg_req)
        raise OnyxError(OnyxErrorCode.CONFLICT, "Recorded the queued turn")

    monkeypatch.setattr("onyx.chat.process_message.prepare_chat_turn", prepare)
    chosen = LLMOverride(model_provider="Provider", model_version="picked-model")
    queued = client.post(
        f"/chat/chat-session/{chat.id}/pending-messages",
        json={
            "message": "Answer with the new model",
            "delivery": "queue",
            "llm_override": chosen.model_dump(),
        },
    )
    assert queued.status_code == 200, queued.text
    assert chat_turn_work.wait_idle(timeout=30)
    assert [request.llm_override for request in started] == [chosen]


def _start_queued_turn(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    **chat_settings: object,
) -> tuple[ChatMessage, list[LLMOverride | None]]:
    """Queue a message after a finished response; return its answer and model."""
    chat_id = response.chat_session_id
    response.response_status = RunStatus.COMPLETE
    chat = db_session.get(ChatSession, chat_id)
    assert chat is not None
    for name, value in chat_settings.items():
        setattr(chat, name, value)
    db_session.commit()
    models: list[LLMOverride | None] = []
    model = QueueTestLLM(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="Done")])
    )

    def get_model(*, llm_override: LLMOverride | None, **_kwargs: object) -> LLM:
        models.append(llm_override)
        return model

    monkeypatch.setattr("onyx.chat.process_message.get_llm_for_persona", get_model)
    queued = client.post(
        f"/chat/chat-session/{chat_id}/pending-messages",
        json={"message": "Queued question", "delivery": "queue"},
    )
    assert queued.status_code == 200, queued.text
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    answer = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == chat_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.id != response.id,
        )
    )
    assert answer is not None
    return answer, models


def test_a_queued_message_without_a_model_uses_the_chat_model(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, models = _start_queued_turn(
        client,
        response,
        db_session,
        monkeypatch,
        current_alternate_model="My Provider__openai__gpt__mini__mc:42",
    )
    assert answer.response_status == RunStatus.COMPLETE
    assert models == [
        LLMOverride(
            model_provider="My Provider",
            model_version="gpt__mini",
            model_configuration_id=42,
        )
    ]


def test_a_queued_turn_checks_access_to_the_saved_document_sets(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access can end while a message waits; the turn saves an error instead."""
    answer, models = _start_queued_turn(
        client,
        response,
        db_session,
        monkeypatch,
        tool_selection=ChatToolSelection(
            internal_search_filters=BaseFilters(document_set=[f"Gone {uuid4()}"])
        ),
    )
    assert answer.response_status == RunStatus.ERROR
    assert models == []


def test_a_queued_turn_runs_without_a_saved_preferred_tool_that_is_gone(
    client: TestClient,
    response: ChatMessage,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer, _models = _start_queued_turn(
        client,
        response,
        db_session,
        monkeypatch,
        tool_selection=ChatToolSelection(preferred_tool_id=2_000_000_000),
    )
    assert answer.response_status == RunStatus.COMPLETE
    assert answer.message == "Done"


def _stream_turn(
    chat: ChatSession, owner: User, message: str, *, accepts_follow_ups: bool = True
) -> None:
    for _packet in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(
            message=message,
            chat_session_id=chat.id,
            accepts_follow_ups=accepts_follow_ups,
        ),
        user=owner,
    ):
        pass
    assert chat_turn_work.wait_idle(timeout=30)


def _idle_worker_with_queued_message(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> ChatSession:
    """Spawn a worker that finishes, then queue a message for it from a store that exited."""

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        if "Initial task" in texts:
            answer = "Follow-up done" if "Follow up" in texts else "Child done"
            return AssistantMessage(content=[TextContent(text=answer)])
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="Started")])
        return AssistantMessage(
            content=[
                ModelToolCall(
                    id="spawn",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"name": "worker", "instruction": "Initial task"},
                )
            ]
        )

    # Agent tools come from the chat agent; persona tools play no part here.
    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    _stream_turn(chat, owner, "Start a worker")
    spawn = db_session.scalar(
        select(ToolCall).where(
            ToolCall.chat_session_id == chat.id, ToolCall.tool_call_id == "spawn"
        )
    )
    assert spawn is not None and spawn.parent_chat_message_id is not None
    worker = db_session.scalar(
        select(ChatSession).where(
            ChatSession.spawned_by_message_id == spawn.parent_chat_message_id
        )
    )
    assert worker is not None
    finished = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == worker.id,
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    assert finished is not None and finished.response_status == RunStatus.COMPLETE
    # A message queued for the idle worker, left by a store that has exited.
    db_session.add(
        ChatInput(
            recipient_session_id=worker.id,
            message_id=str(uuid4()),
            source=InputSource.AGENT,
            invoking_tool_call_id=spawn.id,
            source_response_id=spawn.parent_chat_message_id,
            target_response_id=finished.id,
            root_response_id=spawn.parent_chat_message_id,
            delivery=MessageDelivery.QUEUE,
            content="Follow up",
            max_steps=2,
        )
    )
    db_session.commit()
    return worker


def _root_result_count(db_session: Session, chat_id: UUID) -> int:
    db_session.expire_all()
    return len(
        db_session.scalars(
            select(ChatMessage).where(
                ChatMessage.chat_session_id == chat_id,
                ChatMessage.message_type == MessageType.AGENT_RESULTS,
            )
        ).all()
    )


@pytest.mark.parametrize(
    "host_event", ["none", "over_budget", "stop", "release_while_scanning"]
)
def test_status_starts_child_work_when_no_turn_hosts_it(
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    host_event: str,
) -> None:
    """Child work that becomes startable after every run store exited still starts.

    Status counts it as active agent work, and its dispatch hosts the run. When
    the owner is over budget, the work becomes a visible failed run instead of
    failing silently on every poll. A Stop while the host holds chat admission
    pauses the queue, so a message queued then waits after the host ends. A
    child that finishes during the host's first scan still wakes the root.
    """
    over_budget = host_event == "over_budget"
    worker = _idle_worker_with_queued_message(chat, owner, db_session, monkeypatch)

    if over_budget:

        def over_limit(_user: User) -> None:
            raise OnyxError(OnyxErrorCode.RATE_LIMITED, "Over budget")

        monkeypatch.setattr(
            "onyx.chat.process_message.check_token_rate_limits", over_limit
        )
    queued_ids: list[str] = []
    if host_event == "stop":
        bind = execution.bind_run_store

        def stop_while_hosting(*args: Any, **kwargs: Any) -> Any:
            # The host holds chat admission here; a message and a Stop arrive.
            with get_session_with_current_tenant() as session:
                queued_ids.append(
                    submit_human_message__no_commit(
                        session,
                        chat.id,
                        message="Answer later",
                        delivery=MessageDelivery.QUEUE,
                        target_response_id=None,
                        turn_preparing=False,
                    ).id
                )
                session.commit()
                chat_backend.stop_chat_session(chat.id, None, owner, session)
            return bind(*args, **kwargs)

        monkeypatch.setattr(execution, "bind_run_store", stop_while_hosting)
    root_results_before = _root_result_count(db_session, chat.id)
    if host_event == "release_while_scanning":
        bind = execution.bind_run_store

        def finish_child_during_first_scan(*args: Any, **kwargs: Any) -> Any:
            # Only the host's store; later turns bind their own stores.
            monkeypatch.setattr(execution, "bind_run_store", bind)
            released = Event()
            on_released = kwargs["on_child_released"]

            def child_released() -> None:
                released.set()
                on_released()

            kwargs["on_child_released"] = child_released
            store, view = bind(*args, **kwargs)
            first_scan = store.poll_control

            def scan_until_the_child_is_released() -> None:
                # The child finishes while the host still holds chat admission.
                monkeypatch.setattr(store, "poll_control", first_scan)
                deadline = time.monotonic() + 30
                while not released.is_set():
                    assert time.monotonic() < deadline
                    first_scan()
                    released.wait(0.1)

            monkeypatch.setattr(store, "poll_control", scan_until_the_child_is_released)
            return store, view

        monkeypatch.setattr(execution, "bind_run_store", finish_child_during_first_scan)
    tasks = BackgroundTasks()
    status = chat_backend.get_chat_session_processing_status(
        chat.id, tasks, _NO_HEADERS, owner
    )
    assert status.has_active_subagents
    assert not status.has_startable_input
    asyncio.run(tasks())
    assert chat_turn_work.wait_idle(timeout=30)
    db_session.expire_all()
    if host_event == "stop":
        assert queued_ids
        stopped = db_session.get(ChatSession, chat.id)
        assert stopped is not None and stopped.queue_paused_at is not None
        # The paused queue starts nothing after the host ends.
        assert [
            message.id for message in list_human_messages(db_session, chat.id)
        ] == queued_ids
        assert read_chat_inbox(db_session, chat.id).next_turn is None
    if over_budget:
        failed = db_session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.chat_session_id == worker.id,
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        assert failed is not None and failed.response_status == RunStatus.ERROR
        assert failed.response_failure is not None
        assert failed.response_failure.message == "Over budget"
        assert not read_chat_inbox(db_session, chat.id).child_work
        return
    follow_up = db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.chat_session_id == worker.id,
            ChatMessage.message == "Follow-up done",
        )
    )
    assert follow_up is not None
    assert follow_up.response_status == RunStatus.COMPLETE
    assert follow_up.parent_message is not None
    assert follow_up.parent_message.message == "Follow up"
    status = chat_backend.get_chat_session_processing_status(
        chat.id, BackgroundTasks(), _NO_HEADERS, owner
    )
    assert not status.has_active_subagents
    if host_event == "release_while_scanning":
        # The result started a root follow-up after the host released the chat.
        assert _root_result_count(db_session, chat.id) == root_results_before + 1


def test_one_shot_turns_offer_no_agent_tools(
    chat: ChatSession, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only callers that deliver follow-up responses to a client that shows them
    offer agent tools."""
    offered: list[set[str]] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        offered.append({tool.name for tool in request.tools or []})
        return AssistantMessage(content=[TextContent(text="Done")])

    # Agent tools come from the chat agent; persona tools play no part here.
    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    run_chat_turn(
        new_msg_req=SendMessageRequest(message="One shot", chat_session_id=chat.id),
        user=owner,
    )
    _stream_turn(chat, owner, "Streamed")
    _stream_turn(chat, owner, "Streamed to a client", accepts_follow_ups=False)
    one_shot, streamed, unshown = offered
    assert SPAWN_AGENT_TOOL_NAME not in one_shot
    assert SPAWN_AGENT_TOOL_NAME in streamed
    assert SPAWN_AGENT_TOOL_NAME not in unshown


def test_stop_subagents_drops_work_queued_for_agents(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued messages and results for agents below the root do not start after Stop."""
    worker = _idle_worker_with_queued_message(chat, owner, db_session, monkeypatch)
    assert read_chat_inbox(db_session, chat.id).child_work

    stopped = client.post(f"/chat/chat-session/{chat.id}/stop-subagents")
    assert stopped.status_code == 200, stopped.text
    db_session.expire_all()
    assert not read_chat_inbox(db_session, chat.id).child_work
    assert (
        db_session.scalar(
            select(ChatInput.id).where(ChatInput.recipient_session_id == worker.id)
        )
        is None
    )


def test_stop_subagents_interrupts_unfinished_agents_without_waking_the_root(
    client: TestClient,
    chat: ChatSession,
    owner: User,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = Event(), Event()
    seen: list[str] = []

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        texts = [message.text for message in request.messages]
        if "What happened?" in texts:
            seen.extend(texts)
            return AssistantMessage(content=[TextContent(text="Noted")])
        if "Long task" in texts:
            started.set()
            # The worker runs until its Stop arrives.
            with signal.on_cancel(release.set):
                assert release.wait(30)
            return AssistantMessage(content=[TextContent(text="Too late")])
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="Started")])
        return AssistantMessage(
            content=[
                ModelToolCall(
                    id="spawn",
                    name=SPAWN_AGENT_TOOL_NAME,
                    arguments={"name": "worker", "instruction": "Long task"},
                )
            ]
        )

    monkeypatch.setattr("onyx.chat.execution.construct_tools", lambda **_kwargs: {})
    model = QueueTestLLM(generate)
    monkeypatch.setattr(
        "onyx.chat.process_message.get_llm_for_persona", lambda **_kwargs: model
    )
    try:
        for _packet in handle_stream_message_objects(
            new_msg_req=SendMessageRequest(
                message="Start a worker",
                chat_session_id=chat.id,
                accepts_follow_ups=True,
            ),
            user=owner,
        ):
            pass
        assert started.wait(15)
        stopped = client.post(f"/chat/chat-session/{chat.id}/stop-subagents")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json() == {"stopped_count": 1}
        assert chat_turn_work.wait_idle(timeout=30)
    finally:
        release.set()
    db_session.expire_all()
    worker = db_session.scalar(
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatSession.spawned_by_message_id.in_(
                select(ChatMessage.id).where(ChatMessage.chat_session_id == chat.id)
            ),
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
    )
    assert worker is not None
    assert worker.response_status == RunStatus.CANCELLED
    assert worker.response_failure is not None
    assert worker.response_failure.kind == RunFailureKind.STOPPED_BY_USER
    # The stopped run wakes no agent, so the root gets no follow-up.
    assert (
        db_session.scalar(
            select(ChatMessage.id).where(
                ChatMessage.chat_session_id == chat.id,
                ChatMessage.message_type == MessageType.AGENT_RESULTS,
            )
        )
        is None
    )
    assert read_chat_inbox(db_session, chat.id).next_turn is None
    assert client.post(f"/chat/chat-session/{chat.id}/stop-subagents").json() == {
        "stopped_count": 0
    }
    # A suspended agent waits for its children and would resume; Stop ends it too.
    worker.response_status = RunStatus.SUSPENDED
    db_session.commit()
    assert client.post(f"/chat/chat-session/{chat.id}/stop-subagents").json() == {
        "stopped_count": 1
    }
    db_session.expire_all()
    assert worker.response_status == RunStatus.CANCELLED
    # The root's next step reads the stop as a notice.
    _stream_turn(chat, owner, "What happened?")
    assert any("The user stopped this agent." in text for text in seen)
