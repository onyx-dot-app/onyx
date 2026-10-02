from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheLockLostError
from onyx.chat.chat_processing_checker import (
    PREPARATION_LEASE_SECONDS,
    ChatTurnAdmission,
)
from onyx.chat.incognito_context import IncognitoContext
from onyx.chat.models import (
    ChatHistoryMessage,
    ChatHistoryResult,
)
from onyx.chat.prepare import (
    _resolve_query_processing_hook_result,
    get_custom_agent_prompt,
    prepare_chat_turn,
)
from onyx.chat.prompt_formatting import PromptMetadata
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.enums import IncognitoRecordMode
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.db.models import ChatMessage, ChatSession, Persona, User
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
from onyx.llm.models import AssistantMessage, ReasoningEffort, TextContent, UserMessage
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import PersonaToolConfiguration
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.fakes import FakeCache
from tests.unit.onyx.agents.fakes import ScriptedLLM

# ---------------------------------------------------------------------------
# Query Processing hook response handling (_resolve_query_processing_hook_result)
# ---------------------------------------------------------------------------


def test_hook_skipped_leaves_message_text_unchanged() -> None:
    result = _resolve_query_processing_hook_result(HookSkipped(), "original query")
    assert result == "original query"


def test_hook_soft_failed_leaves_message_text_unchanged() -> None:
    result = _resolve_query_processing_hook_result(HookSoftFailed(), "original query")
    assert result == "original query"


def test_null_query_raises_query_rejected() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=None), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_empty_string_query_raises_query_rejected() -> None:
    """Empty string is falsy — must be treated as rejection, same as None."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=""), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_whitespace_only_query_raises_query_rejected() -> None:
    """Whitespace-only string is truthy but meaningless — must be treated as rejection."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query="   "), "original query"
        )
    assert exc_info.value.error_code is OnyxErrorCode.QUERY_REJECTED


def test_rejection_message_surfaced_in_error_when_provided() -> None:
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(
                query=None, rejection_message="Queries about X are not allowed."
            ),
            "original query",
        )
    assert "Queries about X are not allowed." in str(exc_info.value)


def test_fallback_rejection_message_when_none() -> None:
    """No rejection_message → generic fallback used in OnyxError detail."""
    with pytest.raises(OnyxError) as exc_info:
        _resolve_query_processing_hook_result(
            QueryProcessingResponse(query=None, rejection_message=None),
            "original query",
        )
    assert "No rejection reason was provided." in str(exc_info.value)


def test_nonempty_query_rewrites_message_text() -> None:
    result = _resolve_query_processing_hook_result(
        QueryProcessingResponse(query="rewritten query"), "original query"
    )
    assert result == "rewritten query"


def test_document_set_denial_precedes_session_and_model_creation() -> None:
    from unittest.mock import MagicMock

    from onyx.chat.prepare import prepare_chat_turn
    from onyx.context.search.models import BaseFilters
    from onyx.server.query_and_chat.models import SendMessageRequest

    request = SendMessageRequest(
        message="hello", internal_search_filters=BaseFilters(document_set=["private"])
    )
    user = MagicMock(is_anonymous=False)
    with (
        patch("onyx.chat.prepare.get_session_with_current_tenant"),
        patch(
            "onyx.chat.prepare.filter_document_set_names_by_user_access",
            return_value=[],
        ),
        patch("onyx.chat.prepare.create_chat_session_from_request") as create_session,
        patch("onyx.chat.prepare.get_llm_for_persona") as create_model,
        pytest.raises(OnyxError) as error,
    ):
        prepare_chat_turn(request, user, llm_overrides=None)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    create_session.assert_not_called()
    create_model.assert_not_called()


class TestGetCustomAgentPrompt:
    """Tests for the get_custom_agent_prompt function."""

    def _create_mock_persona(
        self,
        persona_id: int = 1,
        system_prompt: str | None = None,
        replace_base_system_prompt: bool = False,
    ) -> MagicMock:
        """Create a mock Persona with the specified attributes."""
        persona = MagicMock()
        persona.id = persona_id
        persona.system_prompt = system_prompt
        persona.replace_base_system_prompt = replace_base_system_prompt
        return persona

    def _create_mock_chat_session(
        self,
        project: MagicMock | None = None,
    ) -> MagicMock:
        """Create a mock ChatSession with the specified attributes."""
        chat_session = MagicMock()
        chat_session.project = project
        return chat_session

    def _create_mock_project(
        self,
        instructions: str = "",
    ) -> MagicMock:
        """Create a mock UserProject with the specified attributes."""
        project = MagicMock()
        project.instructions = instructions
        return project

    def test_default_persona_no_project(self) -> None:
        """Test that default persona without a project returns None."""
        persona = self._create_mock_persona(persona_id=DEFAULT_PERSONA_ID)
        chat_session = self._create_mock_chat_session(project=None)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result is None

    def test_default_persona_with_project_instructions(self) -> None:
        """Test that default persona in a project returns project instructions."""
        persona = self._create_mock_persona(persona_id=DEFAULT_PERSONA_ID)
        project = self._create_mock_project(instructions="Do X and Y")
        chat_session = self._create_mock_chat_session(project=project)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result == "Do X and Y"

    def test_default_persona_with_empty_project_instructions(self) -> None:
        """Test that default persona in a project with empty instructions returns None."""
        persona = self._create_mock_persona(persona_id=DEFAULT_PERSONA_ID)
        project = self._create_mock_project(instructions="")
        chat_session = self._create_mock_chat_session(project=project)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result is None

    def test_custom_persona_replace_base_prompt_true(self) -> None:
        """Test that custom persona with replace_base_system_prompt=True returns None."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt="Custom system prompt",
            replace_base_system_prompt=True,
        )
        chat_session = self._create_mock_chat_session(project=None)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result is None

    def test_custom_persona_with_system_prompt(self) -> None:
        """Test that custom persona with system_prompt returns the system_prompt."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt="Custom system prompt",
            replace_base_system_prompt=False,
        )
        chat_session = self._create_mock_chat_session(project=None)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result == "Custom system prompt"

    def test_custom_persona_empty_string_system_prompt(self) -> None:
        """Test that custom persona with empty string system_prompt returns None."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt="",
            replace_base_system_prompt=False,
        )
        chat_session = self._create_mock_chat_session(project=None)

        result = get_custom_agent_prompt(persona, chat_session)

        assert result is None

    def test_custom_persona_in_project_uses_persona_prompt(self) -> None:
        """Test that custom persona in a project uses persona's system_prompt, not project instructions."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt="Custom system prompt",
            replace_base_system_prompt=False,
        )
        project = self._create_mock_project(instructions="Project instructions")
        chat_session = self._create_mock_chat_session(project=project)

        result = get_custom_agent_prompt(persona, chat_session)

        # Should use persona's system_prompt, NOT project instructions
        assert result == "Custom system prompt"


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
        "onyx.chat.prepare.get_cache_backend", lambda **_kwargs: FakeCache()
    )
    monkeypatch.setattr("onyx.chat.prepare.get_session_with_current_tenant", Session)
    monkeypatch.setattr(
        "onyx.chat.prepare._load_session",
        lambda *_args: chat_session,
    )
    monkeypatch.setattr(
        "onyx.chat.prepare._select_models", lambda *_args: [(ScriptedLLM([]), "Test")]
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.load_message_branch", lambda *_args: ([parent], parent)
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.execute_hook",
        lambda **_kwargs: QueryProcessingResponse(query="Accepted"),
    )
    tokenizer = MagicMock()
    tokenizer.encode.return_value = [1]
    monkeypatch.setattr("onyx.chat.prepare.get_tokenizer", lambda *_args: tokenizer)
    monkeypatch.setattr(
        "onyx.chat.prepare.create_new_chat_message",
        lambda **_kwargs: ChatMessage(id=2, message_type=MessageType.USER),
    )

    monkeypatch.setattr(
        "onyx.chat.prepare.resolve_context_user_files", lambda *_args: []
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.get_memories",
        lambda *_args: UserMemoryContext(user_info=UserInfo()),
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.get_default_base_system_prompt", lambda *_args: "System"
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.calculate_reserved_tokens", lambda **_kwargs: 100
    )
    monkeypatch.setattr("onyx.chat.prepare.get_tools", lambda *_args: [])
    monkeypatch.setattr(
        "onyx.chat.prepare.find_summary_for_branch", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr("onyx.chat.prepare.prepare_chat_file_inputs", lambda *_args: [])
    monkeypatch.setattr(
        "onyx.chat.prepare.capture_persona_tool_configuration",
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
        "onyx.chat.prepare.capture_chat_history",
        lambda *_args: [
            ChatHistoryMessage(
                id=2,
                message_type=MessageType.USER,
                message="Accepted",
                token_count=8,
                files=[],
                is_clarification=False,
                response_messages=[],
            )
        ],
    )
    monkeypatch.setattr(
        "onyx.chat.prepare.extract_context_files",
        lambda **_kwargs: ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=0,
        ),
    )
    monkeypatch.setattr("onyx.chat.prepare.load_chat_files", lambda _inputs: [])
    monkeypatch.setattr(
        "onyx.chat.prepare.reserve_chat_response_ids", lambda **_kwargs: [3]
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
    monkeypatch.setattr("onyx.chat.prepare.ChatTurnAdmission", lambda _cache: admission)
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
        "onyx.chat.prepare.get_session_with_current_tenant", session_scope
    )

    monkeypatch.setattr("onyx.chat.prepare.extract_context_files", load_files)
    monkeypatch.setattr("onyx.chat.prepare.reserve_chat_response_ids", fail_reservation)
    request = SendMessageRequest(message="Accepted", chat_session_id=session_id)
    user = User(id=uuid4(), email="reader@example.com")
    with ContextThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            lambda: prepare_chat_turn(request, user, llm_overrides=None)
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
        patch("onyx.chat.prepare.get_cache_backend", return_value=cache),
        patch("onyx.chat.prepare.get_session_with_current_tenant"),
        patch(
            "onyx.chat.prepare._load_session",
            return_value=SimpleNamespace(id=session_id, persona=None),
        ),
        patch("onyx.chat.prepare._select_models", side_effect=fail_model_setup),
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
        patch("onyx.chat.prepare.get_cache_backend", return_value=cache),
        patch("onyx.chat.prepare.get_session_with_current_tenant"),
        patch(
            "onyx.chat.prepare._load_session",
            return_value=SimpleNamespace(id=session_id, persona=None),
        ),
        patch("onyx.chat.prepare._select_models") as select_models,
        patch("onyx.chat.prepare.load_message_branch") as load_branch,
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
        patch("onyx.chat.prepare.ChatTurnAdmission", return_value=admission),
        patch(
            "onyx.chat.prepare.execute_hook",
            side_effect=lambda **_kwargs: process_query(),
        ),
        patch("onyx.chat.prepare.get_tokenizer") as tokenizer,
        patch("onyx.chat.prepare.create_new_chat_message") as create_message,
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
        patch("onyx.chat.prepare.load_message_branch", return_value=([parent], parent)),
        patch("onyx.chat.prepare.execute_hook") as query_hook,
        patch("onyx.chat.prepare.get_tokenizer") as tokenizer,
        patch("onyx.chat.prepare.create_new_chat_message") as create_message,
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
        patch("onyx.chat.prepare.ChatTurnAdmission", return_value=admission),
        patch("onyx.chat.prepare.load_chat_files") as load_files,
        patch("onyx.chat.prepare.convert_chat_history") as convert_history,
        patch("onyx.chat.history_store.append_incognito_message") as append_message,
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
def test_incognito_history_keeps_summary_before_stored_messages(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    accepted_text: str | None,
) -> None:
    chat_session.incognito_record_mode = IncognitoRecordMode.USAGE_ONLY
    summary = AssistantMessage(
        content=[TextContent(text="Summary")],
        metadata=PromptMetadata(token_count=1),
    )
    stored = IncognitoContext(
        version=0,
        messages=[
            UserMessage(content="Earlier question"),
            UserMessage(content="Accepted"),
        ],
        previous_run_id="previous-run",
    )
    parent = ChatMessage(
        id=2 if accepted_text is None else 1,
        message_type=MessageType.USER
        if accepted_text is None
        else MessageType.ASSISTANT,
    )
    with (
        patch(
            "onyx.chat.prepare.find_summary_for_branch",
            return_value=ChatMessage(
                message="Summary", token_count=1, last_summarized_message_id=1
            ),
        ),
        patch("onyx.chat.prepare.load_message_branch", return_value=([parent], parent)),
        patch(
            "onyx.chat.prepare.execute_hook",
            return_value=QueryProcessingResponse(query="Accepted"),
        ) as query_hook,
        patch("onyx.chat.history_store.load_incognito_context", return_value=stored),
        patch("onyx.chat.history_store.append_incognito_message") as append_message,
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(
                message=accepted_text or "", chat_session_id=chat_session.id
            ),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    expected = [
        UserMessage(content="Earlier question"),
        UserMessage(content="Accepted"),
    ]
    if accepted_text is not None:
        current_user = setup.input_messages[0]
        assert isinstance(current_user, UserMessage)
        assert current_user.content == accepted_text
        expected.append(current_user)
        append_message.assert_called_once_with(chat_session.id, current_user)
    else:
        append_message.assert_not_called()
    assert setup.messages + setup.input_messages == [summary, *expected]
    assert setup.previous_run_id == "previous-run"
    query_hook.assert_not_called()
    setup.admission.release()


@pytest.mark.parametrize("source_has_user_message", [False, True])
def test_storage_saves_only_new_input_in_its_resolved_format(
    chat_session: ChatSession,
    _mock_chat_preparation: None,
    source_has_user_message: bool,
) -> None:
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
        patch("onyx.chat.prepare.convert_chat_history", return_value=source),
        patch("onyx.chat.prepare.get_chat_history_store", return_value=store),
    ):
        setup = prepare_chat_turn(
            SendMessageRequest(message="Question", chat_session_id=chat_session.id),
            User(id=uuid4(), email="reader@example.com"),
            llm_overrides=None,
        )
    assert setup.input_messages == [stored_user]
    if source_has_user_message:
        store.save_user_message.assert_called_once_with(stored_user)
        assert store.save_user_message.call_args.args[0] is stored_user
    else:
        store.save_user_message.assert_not_called()
    setup.admission.release()
