"""A chat turn reads the user's saved preferences: the instructions and the
memories enter the prompt, the memory tool follows its setting, and the chat
defaults reach the model factory."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.process_message import handle_stream_message_objects
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.memory import add_memory
from onyx.db.models import ChatSession, User
from onyx.db.user_preferences import upsert_user_preferences__no_commit
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    UserChatDefaults,
)
from onyx.server.query_and_chat.models import SendMessageRequest
from tests.external_dependency_unit.chat.test_wait_agents import ScriptedLLM
from tests.external_dependency_unit.conftest import MakeTestUser

INSTRUCTIONS = "Always answer in haiku."
MEMORY = "The user keeps bees."


class ChatTurnRecorder:
    """What one chat turn passed to the model factory, the tool builder and
    the model."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.user_defaults: list[UserChatDefaults | None] = []
        self.enable_memory_tool: list[bool] = []
        self.prompts: list[str] = []

        def generate(
            request: GenerationRequest,
            _signal: CancellationSignal,
        ) -> AssistantMessage:
            self.prompts.append(request.model_dump_json())
            return AssistantMessage(content=[TextContent(text="done")])

        model = ScriptedLLM(generate)

        def get_llm_for_persona(
            *, user_defaults: UserChatDefaults | None, **_kwargs: object
        ) -> ScriptedLLM:
            self.user_defaults.append(user_defaults)
            return model

        def construct_tools(*, enable_memory_tool: bool, **_kwargs: object) -> list:
            self.enable_memory_tool.append(enable_memory_tool)
            return []

        monkeypatch.setattr(
            "onyx.chat.process_message.get_llm_for_persona", get_llm_for_persona
        )
        monkeypatch.setattr("onyx.chat.execution.construct_tools", construct_tools)


def _chat(db_session: Session, user: User) -> ChatSession:
    chat = ChatSession(
        id=uuid4(),
        user_id=user.id,
        persona_id=DEFAULT_PERSONA_ID,
        description="Chat with saved preferences",
    )
    db_session.add(chat)
    db_session.commit()
    return chat


def _send(chat: ChatSession, user: User) -> None:
    for _packet in handle_stream_message_objects(
        new_msg_req=SendMessageRequest(message="Hello", chat_session_id=chat.id),
        user=user,
    ):
        pass


@pytest.mark.parametrize("memories_on", [True, False])
def test_chat_turn_reads_saved_preferences(
    db_session: Session,
    make_test_user: MakeTestUser,
    monkeypatch: pytest.MonkeyPatch,
    memories_on: bool,
) -> None:
    user = make_test_user("chat_user_preferences")
    add_memory(user.id, MEMORY, db_session)
    upsert_user_preferences__no_commit(
        db_session,
        user.id,
        instructions=INSTRUCTIONS,
        use_memories=memories_on,
        enable_memory_tool=memories_on,
        temperature_default=0.3,
    )
    db_session.commit()
    recorder = ChatTurnRecorder(monkeypatch)

    _send(_chat(db_session, user), user)

    assert recorder.user_defaults == [UserChatDefaults(temperature_default=0.3)]
    assert recorder.enable_memory_tool == [memories_on]
    assert recorder.prompts
    prompt = recorder.prompts[0]
    assert INSTRUCTIONS in prompt
    assert (MEMORY in prompt) is memories_on


def test_chat_turn_uses_defaults_without_saved_preferences(
    db_session: Session,
    make_test_user: MakeTestUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_test_user("chat_default_preferences")
    add_memory(user.id, MEMORY, db_session)
    recorder = ChatTurnRecorder(monkeypatch)

    _send(_chat(db_session, user), user)

    assert recorder.user_defaults == [UserChatDefaults()]
    assert recorder.enable_memory_tool == [True]
    assert MEMORY in recorder.prompts[0]
