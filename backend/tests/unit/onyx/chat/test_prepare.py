from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import AvailableFiles, ChatHistoryMessage, PersonaPromptConfig
from onyx.chat.prepare import (
    _ChatPreparation,
    _resolve_query_processing_hook_result,
    get_custom_agent_prompt,
    prepare_chat_turn,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ExtractedContextFiles, UserFileMetadata
from onyx.hooks.executor import HookSkipped, HookSoftFailed
from onyx.hooks.points.query_processing import QueryProcessingResponse
from onyx.llm.models import ReasoningEffort
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.tools.models import PersonaToolConfiguration
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
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


def test_attachment_loading_releases_preparation_session_before_reservation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    active_sessions = 0
    reservation_attempted = False
    session_id = uuid4()
    model = ScriptedLLM([])
    prepared = _ChatPreparation(
        session_id=session_id,
        project_id=None,
        incognito_record_mode=None,
        persona_id=1,
        persona=PersonaPromptConfig(
            system_prompt=None,
            task_prompt=None,
            datetime_aware=False,
            replace_base_system_prompt=False,
        ),
        base_system_prompt="System",
        tool_configuration=PersonaToolConfiguration(
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
        research_tool_id=None,
        selected_models=[(model, "Test")],
        history=[
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
        file_inputs=[],
        context_user_files=[],
        available_files=AvailableFiles(),
        user_message_id=2,
        accepted_text="Accepted",
        user_memory_context=UserMemoryContext(user_info=UserInfo()),
        custom_agent_prompt=None,
        reserved_token_count=100,
        reasoning_effort=ReasoningEffort.LOW,
        forced_tool_id=None,
        search_tool_id=None,
        summary=None,
        summarized_file_metadata={},
        skip_clarification=True,
    )

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
    monkeypatch.setattr(
        "onyx.chat.prepare._prepare_chat_data", lambda *_args, **_kwargs: prepared
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
        with pytest.raises(RuntimeError, match="Response reservation failed"):
            pending.result(timeout=5)
    assert reservation_attempted
    assert active_sessions == 0
