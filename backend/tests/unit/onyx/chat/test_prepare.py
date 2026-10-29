import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from typing import cast
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.agents.models import RunStatus
from onyx.cache.interface import CacheLockLostError
from onyx.chat.chat_processing_checker import (
    PREPARATION_LEASE_SECONDS,
    ChatTurnAdmission,
)
from onyx.chat.models import (
    ChatHistoryMessage,
    ChatHistoryResult,
    IncognitoContext,
)
from onyx.chat.process_message import (
    _process_query,
    prepare_chat_turn,
)
from onyx.chat.prompt_utils import build_chat_prompt, prepare_prompt
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.context.models import UserInfo, UserMemoryContext
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.enums import IncognitoRecordMode
from onyx.db.models import ChatMessage, ChatSession, Persona, User, UserProject
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import (
    ChatFileInput,
    ChatLoadedFile,
    ExtractedContextFiles,
    UserFileMetadata,
)
from onyx.hooks.executor import HookSkipped, HookSoftFailed
from onyx.hooks.points.query_processing import QueryProcessingResponse
from onyx.llm.models import ReasoningEffort, SystemMessage, UserMessage
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import PersonaToolConfiguration
from tests.unit.fakes import FakeCache
from tests.unit.onyx.agents.fakes import ScriptedLLM


@pytest.mark.parametrize(
    "hook_result, expected",
    [
        (HookSkipped(), "original query"),
        (HookSoftFailed(), "original query"),
        (QueryProcessingResponse(query="  rewritten query  "), "rewritten query"),
    ],
)
def test_process_query_applies_hook_result(
    chat_session: ChatSession,
    hook_result: QueryProcessingResponse | HookSkipped | HookSoftFailed,
    expected: str,
) -> None:
    with patch("onyx.chat.process_message.execute_hook", return_value=hook_result):
        result = _process_query(
            "original query",
            chat_session,
            User(id=uuid4(), email="reader@example.com"),
            MagicMock(spec=Session),
        )
    assert result == expected


@pytest.mark.parametrize("query", [None, "", "   "])
@pytest.mark.parametrize(
    "rejection_message", [None, "Queries about X are not allowed."]
)
def test_process_query_rejects_empty_hook_query(
    chat_session: ChatSession, query: str | None, rejection_message: str | None
) -> None:
    with (
        patch(
            "onyx.chat.process_message.execute_hook",
            return_value=QueryProcessingResponse(
                query=query, rejection_message=rejection_message
            ),
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _process_query(
            "original query",
            chat_session,
            User(id=uuid4(), email="reader@example.com"),
            MagicMock(spec=Session),
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED
    assert (rejection_message or "No rejection reason was provided.") in str(
        exc_info.value
    )


def test_document_set_denial_precedes_session_and_model_creation() -> None:
    from unittest.mock import MagicMock

    from onyx.chat.process_message import prepare_chat_turn
    from onyx.context.search.models import BaseFilters
    from onyx.server.query_and_chat.models import SendMessageRequest

    request = SendMessageRequest(
        message="hello", internal_search_filters=BaseFilters(document_set=["private"])
    )
    user = MagicMock(is_anonymous=False)
    with (
        patch("onyx.chat.process_message.get_session_with_current_tenant"),
        patch(
            "onyx.chat.process_message.filter_document_set_names_by_user_access",
            return_value=[],
        ),
        patch(
            "onyx.chat.process_message.create_chat_session_from_request"
        ) as create_session,
        patch("onyx.chat.process_message.get_llm_for_persona") as create_model,
        pytest.raises(OnyxError) as error,
    ):
        prepare_chat_turn(request, user, llm_overrides=None)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    create_session.assert_not_called()
    create_model.assert_not_called()


@pytest.mark.parametrize(
    "persona_id, agent_prompt, project_prompt, replace_base, expected",
    [
        (DEFAULT_PERSONA_ID, None, None, False, None),
        (DEFAULT_PERSONA_ID, None, "Do X and Y", False, "Do X and Y"),
        (DEFAULT_PERSONA_ID, None, "", False, None),
        (1, "Custom system prompt", None, True, None),
        (1, "Custom system prompt", None, False, "Custom system prompt"),
        (1, "", None, False, None),
        (1, None, None, False, None),
        (
            1,
            "Custom system prompt",
            "Project instructions",
            False,
            "Project instructions:\nProject instructions\n\n"
            "Agent instructions:\nCustom system prompt\n\n"
            "If these instructions conflict, follow the agent instructions.",
        ),
        (
            1,
            "Custom system prompt",
            "Project instructions",
            True,
            "Project instructions",
        ),
        (1, "", "Project instructions", False, "Project instructions"),
    ],
)
def test_preparation_combines_project_and_agent_instructions(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    persona_id: int,
    agent_prompt: str | None,
    project_prompt: str | None,
    replace_base: bool,
    expected: str | None,
) -> None:
    chat_session.persona.id = persona_id
    chat_session.persona.system_prompt = agent_prompt
    chat_session.persona.replace_base_system_prompt = replace_base
    if project_prompt is not None:
        chat_session.project = UserProject(instructions=project_prompt)
    setup = prepare_chat_turn(
        SendMessageRequest(message="Question", chat_session_id=chat_session.id),
        User(id=uuid4(), email="reader@example.com"),
        llm_overrides=None,
    )
    assert setup.custom_agent_prompt == expected
    setup.admission.release()


@pytest.fixture
def chat_session() -> ChatSession:
    return ChatSession(
        id=uuid4(),
        persona=Persona(
            id=1,
            name="Assistant",
            system_prompt=None,
            task_prompt=None,
            datetime_aware=False,
            replace_base_system_prompt=False,
        ),
        reasoning_effort_override=ReasoningEffort.LOW,
    )


@pytest.fixture
def _mock_chat_preparation(
    monkeypatch: pytest.MonkeyPatch, chat_session: ChatSession
) -> None:
    parent = ChatMessage(
        id=1, message_type=MessageType.ASSISTANT, is_clarification=False
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.incognito_session_ended", lambda _id: False
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_cache_backend", lambda **_kwargs: FakeCache()
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_session_with_current_tenant", Session
    )
    monkeypatch.setattr(
        "onyx.chat.process_message._load_session",
        lambda *_args: chat_session,
    )
    monkeypatch.setattr(
        "onyx.chat.process_message._select_models",
        lambda *_args: [(ScriptedLLM([]), "Test")],
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.load_message_branch",
        lambda *_args: ([parent], parent),
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.execute_hook",
        lambda **_kwargs: QueryProcessingResponse(query="Accepted"),
    )
    tokenizer = MagicMock()
    tokenizer.encode.return_value = [1]
    monkeypatch.setattr(
        "onyx.chat.process_message.get_tokenizer", lambda *_args: tokenizer
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.create_new_chat_message",
        lambda **_kwargs: ChatMessage(id=2, message_type=MessageType.USER),
    )

    monkeypatch.setattr(
        "onyx.chat.process_message.resolve_context_user_files", lambda *_args: []
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_memories",
        lambda *_args: UserMemoryContext(user_info=UserInfo()),
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.get_default_base_system_prompt",
        lambda *_args: "System",
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.calculate_reserved_tokens", lambda **_kwargs: 100
    )
    monkeypatch.setattr("onyx.chat.process_message.get_tools", lambda *_args: [])
    monkeypatch.setattr(
        "onyx.chat.process_message.find_summary_for_branch",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.prepare_chat_file_inputs", lambda *_args: []
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.capture_persona_tool_configuration",
        lambda _persona: PersonaToolConfiguration(
            persona_id=1,
            persona_name="Assistant",
            tools=[],
            search=PersonaSearchInfo(
                document_set_names=[],
                search_start_date=None,
                attached_document_ids=[],
                hierarchy_node_ids=[],
            ),
        ),
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.capture_chat_history",
        lambda _messages, _tools, _tokens, checkpoint: [
            ChatHistoryMessage(
                id=2,
                message_type=MessageType.USER,
                message="Accepted",
                token_count=8,
                files=[],
                is_clarification=False,
                response_messages=[],
                checkpoint=checkpoint,
            )
        ],
    )
    monkeypatch.setattr(
        "onyx.chat.process_message.extract_context_files",
        lambda **_kwargs: ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=0,
        ),
    )
    monkeypatch.setattr("onyx.chat.process_message.load_chat_files", lambda _inputs: [])
    monkeypatch.setattr(
        "onyx.chat.process_message.reserve_chat_response_ids", lambda **_kwargs: [3]
    )


@pytest.mark.parametrize("expired_during_file_loading", [False, True])
def test_attachment_loading_releases_preparation_session_before_reservation_failure(
    monkeypatch: pytest.MonkeyPatch,
    expired_during_file_loading: bool,
    chat_session: ChatSession,
    _mock_chat_preparation: None,
) -> None:
    cache = FakeCache()
    admission = ChatTurnAdmission(cache)
    monkeypatch.setattr(
        "onyx.chat.process_message.ChatTurnAdmission", lambda _cache: admission
    )
    started = Event()
    release = Event()
    active_sessions = 0
    reservation_attempted = False
    session_id = chat_session.id

    @contextmanager
    def session_scope() -> Iterator[Session]:
        nonlocal active_sessions
        active_sessions += 1
        try:
            with Session() as session:
                yield session
        finally:
            active_sessions -= 1

    def load_files(
        user_files: list[UserFileMetadata],
        llm_max_context_window: int,
        reserved_token_count: int,
    ) -> ExtractedContextFiles:
        del user_files, llm_max_context_window, reserved_token_count
        started.set()
        assert release.wait(5)
        if expired_during_file_loading:
            admission._last_refresh -= PREPARATION_LEASE_SECONDS
        return ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=0,
        )

    def fail_reservation(
        db_session: Session,
        chat_session_id: UUID,
        parent_message_id: int,
        model_display_names: list[str],
    ) -> list[int]:
        nonlocal reservation_attempted
        del db_session, chat_session_id, model_display_names
        reservation_attempted = True
        assert active_sessions == 1
        assert parent_message_id == 2
        raise RuntimeError("Response reservation failed")

    monkeypatch.setattr(
        "onyx.chat.process_message.get_session_with_current_tenant", session_scope
    )

    monkeypatch.setattr("onyx.chat.process_message.extract_context_files", load_files)
    monkeypatch.setattr(
        "onyx.chat.process_message.reserve_chat_response_ids", fail_reservation
    )
    request = SendMessageRequest(message="Accepted", chat_session_id=session_id)
    user = User(id=uuid4(), email="reader@example.com")
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            contextvars.copy_context().run,
            lambda: prepare_chat_turn(request, user, llm_overrides=None),
        )
        try:
            assert started.wait(5)
            assert active_sessions == 0
            assert not reservation_attempted
        finally:
            release.set()
        if expired_during_file_loading:
            with pytest.raises(CacheLockLostError, match="renewal expired"):
                pending.result(timeout=5)
        else:
            with pytest.raises(RuntimeError, match="Response reservation failed"):
                pending.result(timeout=5)
    assert reservation_attempted is not expired_during_file_loading
    assert active_sessions == 0


def test_admission_precedes_model_setup_and_releases_after_setup_failure() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from onyx.chat.chat_processing_checker import is_chat_session_processing
    from onyx.server.query_and_chat.models import SendMessageRequest
    from tests.unit.fakes import FakeCache

    cache = FakeCache()
    session_id = uuid4()
    request = SendMessageRequest(message="hello", chat_session_id=session_id)

    def fail_model_setup(*_args: object) -> None:
        assert is_chat_session_processing(session_id, cache)
        raise RuntimeError("model setup failed")

    with (
        patch("onyx.chat.process_message.get_cache_backend", return_value=cache),
        patch("onyx.chat.process_message.get_session_with_current_tenant"),
        patch(
            "onyx.chat.process_message._load_session",
            return_value=SimpleNamespace(id=session_id, persona=None),
        ),
        patch("onyx.chat.process_message._select_models", side_effect=fail_model_setup),
        pytest.raises(RuntimeError, match="model setup failed"),
    ):
        prepare_chat_turn(request, MagicMock(), llm_overrides=None)
    assert not is_chat_session_processing(session_id, cache)


def test_busy_session_rejects_before_model_or_history_setup() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from uuid import uuid4

    from onyx.chat.chat_processing_checker import (
        ChatTurnAdmission,
        is_chat_session_processing,
    )
    from onyx.server.query_and_chat.models import SendMessageRequest
    from tests.unit.fakes import FakeCache

    cache = FakeCache()
    session_id = uuid4()
    admitted = ChatTurnAdmission(cache)
    admitted.claim(session_id)
    request = SendMessageRequest(message="hello", chat_session_id=session_id)
    with (
        patch("onyx.chat.process_message.get_cache_backend", return_value=cache),
        patch("onyx.chat.process_message.get_session_with_current_tenant"),
        patch(
            "onyx.chat.process_message._load_session",
            return_value=SimpleNamespace(id=session_id, persona=None),
        ),
        patch("onyx.chat.process_message._select_models") as select_models,
        patch("onyx.chat.process_message.load_message_branch") as load_branch,
        pytest.raises(OnyxError) as error,
    ):
        prepare_chat_turn(request, MagicMock(), llm_overrides=None)
    assert error.value.error_code is OnyxErrorCode.CONFLICT
    select_models.assert_not_called()
    load_branch.assert_not_called()
    assert is_chat_session_processing(session_id, cache)
    admitted.release()


@pytest.mark.parametrize("expires_in_hook", [False, True])
def test_expired_preparation_does_not_save_user_message(
    expires_in_hook: bool,
    chat_session: ChatSession,
    _mock_chat_preparation: None,
) -> None:
    admission = ChatTurnAdmission(FakeCache())

    def process_query() -> QueryProcessingResponse:
        if expires_in_hook:
            admission._last_refresh -= PREPARATION_LEASE_SECONDS
        return QueryProcessingResponse(query="Accepted")

    def tokenize(_text: str) -> list[int]:
        if not expires_in_hook:
            admission._last_refresh -= PREPARATION_LEASE_SECONDS
        return [1]

    with (
        patch("onyx.chat.process_message.ChatTurnAdmission", return_value=admission),
        patch(
            "onyx.chat.process_message.execute_hook",
            side_effect=lambda **_kwargs: process_query(),
        ),
        patch("onyx.chat.process_message.get_tokenizer") as tokenizer,
        patch("onyx.chat.process_message.create_new_chat_message") as create_message,
    ):
        tokenizer.return_value.encode.side_effect = tokenize
        with pytest.raises(CacheLockLostError, match="renewal expired"):
            prepare_chat_turn(
                SendMessageRequest(message="Question", chat_session_id=chat_session.id),
                User(id=uuid4(), email="reader@example.com"),
                llm_overrides=None,
            )
    create_message.assert_not_called()


def test_regeneration_reuses_user_message_without_writing(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
) -> None:
    parent = ChatMessage(id=2, message_type=MessageType.USER)
    with (
        patch(
            "onyx.chat.process_message.load_message_branch",
            return_value=([parent], parent),
        ),
        patch("onyx.chat.process_message.execute_hook") as query_hook,
        patch("onyx.chat.process_message.get_tokenizer") as tokenizer,
        patch("onyx.chat.process_message.create_new_chat_message") as create_message,
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(message="Question", chat_session_id=chat_session.id),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    assert setup.user_message_id == parent.id
    assert len(setup.input_messages) == 1
    assert isinstance(setup.input_messages[0], UserMessage)
    assert setup.input_messages[0].content == "Accepted"
    query_hook.assert_not_called()
    tokenizer.assert_not_called()
    create_message.assert_not_called()
    setup.admission.release()


@pytest.mark.parametrize("expiry_stage", ["files", "conversion", "history_load"])
def test_expired_history_preparation_cannot_append_after_new_owner_claims(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    expiry_stage: str,
) -> None:
    cache = FakeCache()
    admission = ChatTurnAdmission(cache)
    next_admission = ChatTurnAdmission(cache)
    chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY

    def replace_owner() -> None:
        cache.delete(ChatTurnAdmission._owner_key(chat_session.id))
        next_admission.claim(chat_session.id)

    converted = ChatHistoryResult(
        messages=[UserMessage(content="Accepted")], all_injected_file_metadata={}
    )
    with (
        patch("onyx.chat.process_message.ChatTurnAdmission", return_value=admission),
        patch("onyx.chat.process_message.load_chat_files") as load_files,
        patch("onyx.chat.process_message.convert_chat_history") as convert_history,
        patch("onyx.chat.history_store.save_incognito_user_message") as append_message,
        patch("onyx.chat.history_store.load_incognito_context") as load_history,
    ):

        def load(_file_inputs: list[ChatFileInput]) -> list[ChatLoadedFile]:
            if expiry_stage == "files":
                replace_owner()
            return []

        def convert() -> ChatHistoryResult:
            if expiry_stage == "conversion":
                replace_owner()
            return converted

        def load_stored(_session_id: UUID) -> IncognitoContext:
            if expiry_stage == "history_load":
                replace_owner()
            return IncognitoContext(version=0, messages=[])

        load_files.side_effect = load
        convert_history.side_effect = lambda **_kwargs: convert()
        load_history.side_effect = load_stored
        with pytest.raises(CacheLockLostError, match="admission was lost"):
            prepare_chat_turn(
                SendMessageRequest(message="Question", chat_session_id=chat_session.id),
                User(id=uuid4(), email="reader@example.com"),
                llm_overrides=None,
            )
    append_message.assert_not_called()
    next_admission.refresh()
    next_admission.release()


@pytest.mark.parametrize("accepted_text", [None, "", "Accepted"])
def test_incognito_history_retains_summary_checkpoint(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    accepted_text: str | None,
) -> None:
    chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    stored = IncognitoContext(
        version=0,
        messages=[
            UserMessage(id="chat:1", content="Earlier question"),
            UserMessage(id="chat:2", content="Accepted"),
        ],
        previous_run_id="previous-run",
    )
    parent = ChatMessage(
        id=2 if accepted_text is None else 1,
        is_clarification=False,
        message_type=MessageType.USER
        if accepted_text is None
        else MessageType.ASSISTANT,
    )
    with (
        patch(
            "onyx.chat.process_message.find_summary_for_branch",
            return_value=ChatMessage(
                id=3,
                message="Summary",
                token_count=1,
                last_summarized_message_id="chat:1",
            ),
        ),
        patch(
            "onyx.chat.process_message.load_message_branch",
            return_value=([parent], parent),
        ),
        patch(
            "onyx.chat.process_message.execute_hook",
            return_value=QueryProcessingResponse(query="Accepted"),
        ) as query_hook,
        patch("onyx.chat.history_store.load_incognito_context", return_value=stored),
        patch("onyx.chat.history_store.save_incognito_user_message") as append_message,
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(
                message=accepted_text or "", chat_session_id=chat_session.id
            ),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    expected = [
        UserMessage(id="chat:1", content="Earlier question"),
        UserMessage(id="chat:2", content="Accepted"),
    ]
    if accepted_text is not None:
        current_user = setup.input_messages[0]
        assert isinstance(current_user, UserMessage)
        assert current_user.content == accepted_text
        expected.append(current_user)
        append_message.assert_called_once_with(chat_session.id, current_user)
    else:
        append_message.assert_called_once_with(chat_session.id, setup.input_messages[0])
    assert setup.messages + setup.input_messages == expected
    assert setup.checkpoint is not None
    assert setup.checkpoint.summary == "Summary"
    assert setup.checkpoint.covered_through_message_id == "chat:1"
    assert setup.previous_run_id == (
        "previous-run" if accepted_text is not None else None
    )
    query_hook.assert_not_called()
    setup.admission.release()


@pytest.mark.parametrize("source_has_user_message", [False, True])
def test_storage_saves_its_resolved_input(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    source_has_user_message: bool,
) -> None:
    chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    source = ChatHistoryResult(
        messages=[UserMessage(content="Prompt with attachments")]
        if source_has_user_message
        else [],
        all_injected_file_metadata={},
    )
    stored_user = UserMessage(content="Backend-normalized input")
    store = MagicMock()
    store.prepare_messages.return_value = ([stored_user], "prior-run")
    with (
        patch("onyx.chat.process_message.convert_chat_history", return_value=source),
        patch("onyx.chat.process_message.get_chat_history_store", return_value=store),
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(message="Question", chat_session_id=chat_session.id),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    assert setup.input_messages == [stored_user]
    store.save_user_message.assert_called_once_with(stored_user)
    assert store.save_user_message.call_args.args[0] is stored_user
    setup.admission.release()


@pytest.mark.parametrize("stage", ["_select_models", "convert_chat_history"])
def test_expired_preparation_cannot_write_next_message(
    monkeypatch: pytest.MonkeyPatch,
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    stage: str,
) -> None:
    import onyx.chat.process_message as preparation

    admission = ChatTurnAdmission(FakeCache())
    monkeypatch.setattr(preparation, "ChatTurnAdmission", lambda _cache: admission)
    operation = cast(
        Callable[..., object],
        preparation._select_models
        if stage == "_select_models"
        else preparation.convert_chat_history,
    )

    def expire(*args: object, **kwargs: object) -> object:
        result = operation(*args, **kwargs)
        admission._last_refresh -= PREPARATION_LEASE_SECONDS
        return result

    next_write = (
        "create_new_chat_message"
        if stage == "_select_models"
        else "reserve_chat_response_ids"
    )
    with (
        patch.object(preparation, stage, side_effect=expire),
        patch.object(preparation, next_write) as write,
        pytest.raises(CacheLockLostError, match="renewal expired"),
    ):
        prepare_chat_turn(
            SendMessageRequest(message="Question", chat_session_id=chat_session.id),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    write.assert_not_called()


def test_preparation_uses_selected_recorded_response_as_predecessor(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
) -> None:
    recorded = ChatMessage(
        id=7,
        message_type=MessageType.ASSISTANT,
        response_status=RunStatus.CANCELLED,
        is_clarification=False,
    )
    legacy = ChatMessage(
        id=8, message_type=MessageType.ASSISTANT, is_clarification=False
    )
    with patch(
        "onyx.chat.process_message.load_message_branch",
        return_value=([recorded, legacy], legacy),
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(message="Next", chat_session_id=chat_session.id),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    assert setup.previous_run_id == "7"
    setup.admission.release()


def test_incognito_preparation_rejects_ended_context_before_reserving_response(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
) -> None:
    chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    with (
        patch("onyx.chat.process_message.incognito_session_ended", return_value=True),
        patch(
            "onyx.chat.history_store.load_incognito_context",
            return_value=IncognitoContext(version=0, messages=[]),
        ),
        patch("onyx.chat.history_store.save_incognito_user_message"),
        patch(
            "onyx.chat.process_message.reserve_chat_response_ids"
        ) as reserve_response,
    ):
        with pytest.raises(RuntimeError, match="Incognito session ended"):
            prepare_chat_turn(
                SendMessageRequest(message="Question", chat_session_id=chat_session.id),
                User(id=uuid4(), email="reader@example.com"),
                llm_overrides=None,
            )
    reserve_response.assert_not_called()


@pytest.mark.parametrize("replace_base", [False, True])
@pytest.mark.parametrize("base_prompt", ["Base prompt", ""])
def test_project_instructions_supplement_agent_prompt(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    replace_base: bool,
    base_prompt: str,
) -> None:
    chat_session.persona.system_prompt = "Answer tersely."
    chat_session.persona.replace_base_system_prompt = replace_base
    chat_session.project = UserProject(instructions="Use the project glossary.")
    setup = prepare_chat_turn(
        SendMessageRequest(message="Question", chat_session_id=chat_session.id),
        User(id=uuid4(), email="reader@example.com"),
        llm_overrides=None,
    )
    setup.admission.release()
    prompt = build_chat_prompt(
        tools=[],
        persona=setup.persona,
        custom_prompt=setup.custom_agent_prompt,
        base_prompt=base_prompt,
        files=setup.extracted_context_files,
        memory=None,
        inject_memories=False,
        reminders_enabled=False,
        results=[],
        previous_results=[],
        is_last_step=False,
        ran_image_gen=False,
    )
    history = prepare_prompt(
        [UserMessage(content="Question")],
        system_prompt=prompt.system_prompt,
        custom_agent_prompt=prompt.custom_prompt,
        reminder_message=None,
        context_files=setup.extracted_context_files,
        token_counter=len,
    )
    text = "\n".join(message.text for message in history)
    assert text.count("Answer tersely.") == 1
    assert text.count("Use the project glossary.") == 1
    assert history[-1].text == "Question"
    if replace_base:
        assert isinstance(history[0], SystemMessage)
        assert history[0].text == "Answer tersely."
        assert isinstance(history[1], UserMessage)
        assert history[1].text == "Use the project glossary."
        assert "Base prompt" not in text
    elif base_prompt:
        assert isinstance(history[1], UserMessage)
    else:
        assert isinstance(history[0], SystemMessage)
