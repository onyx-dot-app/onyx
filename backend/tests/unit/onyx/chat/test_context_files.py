"""Tests for the unified context file extraction logic (Phase 5).

Covers:
- resolve_context_user_files: precedence rule (custom persona supersedes project)
- extract_context_files: all-or-nothing context window fit check
- Search filter / search_usage determination in the caller
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

from onyx.chat.models import ExtractedContextFiles
from onyx.chat.process_message import determine_search_params
from onyx.chat.process_message import extract_context_files
from onyx.chat.process_message import resolve_context_user_files
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.models import UserFile
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.tools.models import SearchToolUsage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_file(
    token_count: int = 100,
    name: str = "file.txt",
    file_id: str | None = None,
) -> UserFile:
    file_uuid = UUID(file_id) if file_id else uuid4()
    return UserFile(
        id=file_uuid,
        file_id=str(file_uuid),
        name=name,
        token_count=token_count,
    )


def _make_persona(
    persona_id: int,
    user_files: list | None = None,
) -> MagicMock:
    persona = MagicMock()
    persona.id = persona_id
    persona.user_files = user_files or []
    return persona


def _make_in_memory_file(
    file_id: str,
    content: str = "hello world",
    file_type: ChatFileType = ChatFileType.PLAIN_TEXT,
    filename: str = "file.txt",
) -> InMemoryChatFile:
    return InMemoryChatFile(
        file_id=file_id,
        content=content.encode("utf-8"),
        file_type=file_type,
        filename=filename,
    )


# ===========================================================================
# resolve_context_user_files
# ===========================================================================


class TestResolveContextUserFiles:
    """Precedence rule: custom persona fully supersedes project."""

    def test_custom_persona_with_files_returns_persona_files(self) -> None:
        persona_files = [_make_user_file(), _make_user_file()]
        persona = _make_persona(persona_id=42, user_files=persona_files)
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=99, user_id=uuid4(), db_session=db_session
        )

        assert result == persona_files

    def test_custom_persona_without_files_returns_empty(self) -> None:
        """Custom persona with no files should NOT fall through to project."""
        persona = _make_persona(persona_id=42, user_files=[])
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=99, user_id=uuid4(), db_session=db_session
        )

        assert result == []

    def test_custom_persona_none_files_returns_empty(self) -> None:
        """Custom persona with user_files=None should NOT fall through."""
        persona = _make_persona(persona_id=42, user_files=None)
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=99, user_id=uuid4(), db_session=db_session
        )

        assert result == []

    @patch("onyx.chat.process_message.get_user_files_from_project")
    def test_default_persona_in_project_returns_project_files(
        self, mock_get_files: MagicMock
    ) -> None:
        project_files = [_make_user_file(), _make_user_file()]
        mock_get_files.return_value = project_files
        persona = _make_persona(persona_id=DEFAULT_PERSONA_ID)
        user_id = uuid4()
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=99, user_id=user_id, db_session=db_session
        )

        assert result == project_files
        mock_get_files.assert_called_once_with(
            project_id=99, user_id=user_id, db_session=db_session
        )

    def test_default_persona_no_project_returns_empty(self) -> None:
        persona = _make_persona(persona_id=DEFAULT_PERSONA_ID)
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=None, user_id=uuid4(), db_session=db_session
        )

        assert result == []

    @patch("onyx.chat.process_message.get_user_files_from_project")
    def test_custom_persona_without_files_ignores_project(
        self, mock_get_files: MagicMock
    ) -> None:
        """Even with a project_id, custom persona means project is invisible."""
        persona = _make_persona(persona_id=7, user_files=[])
        db_session = MagicMock()

        result = resolve_context_user_files(
            persona=persona, project_id=99, user_id=uuid4(), db_session=db_session
        )

        assert result == []
        mock_get_files.assert_not_called()


# ===========================================================================
# extract_context_files
# ===========================================================================


class TestExtractContextFiles:
    """All-or-nothing context window fit check."""

    def test_empty_user_files_returns_empty(self) -> None:
        db_session = MagicMock()
        result = extract_context_files(
            user_files=[],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=db_session,
        )
        assert result.file_texts == []
        assert result.image_files == []
        assert result.use_as_search_filter is False
        assert result.uncapped_token_count is None

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_files_fit_in_context_are_loaded(self, mock_load: MagicMock) -> None:
        file_id = str(uuid4())
        uf = _make_user_file(token_count=100, file_id=file_id)
        mock_load.return_value = [
            _make_in_memory_file(file_id=file_id, content="file content")
        ]

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.file_texts == ["file content"]
        assert result.use_as_search_filter is False
        assert result.total_token_count == 100
        assert len(result.file_metadata) == 1
        assert result.file_metadata[0].file_id == file_id

    def test_files_overflow_context_not_loaded(self) -> None:
        """When aggregate tokens exceed 60% of available window, nothing is loaded."""
        uf = _make_user_file(token_count=7000)

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.file_texts == []
        assert result.image_files == []
        assert result.use_as_search_filter is True
        assert result.uncapped_token_count == 7000
        assert result.total_token_count == 0

    def test_overflow_boundary_exact(self) -> None:
        """Token count exactly at the 60% boundary should trigger overflow."""
        # Available = (10000 - 0) * 0.6 = 6000. Tokens = 6000 → >= threshold.
        uf = _make_user_file(token_count=6000)

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.use_as_search_filter is True

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_just_under_boundary_loads(self, mock_load: MagicMock) -> None:
        """Token count just under the 60% boundary should load files."""
        file_id = str(uuid4())
        uf = _make_user_file(token_count=5999, file_id=file_id)
        mock_load.return_value = [_make_in_memory_file(file_id=file_id, content="data")]

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.use_as_search_filter is False
        assert result.file_texts == ["data"]

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_multiple_files_aggregate_check(self, mock_load: MagicMock) -> None:
        """Multiple small files that individually fit but collectively overflow."""
        files = [_make_user_file(token_count=2500) for _ in range(3)]
        # 3 * 2500 = 7500 > 6000 threshold

        result = extract_context_files(
            user_files=files,
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.use_as_search_filter is True
        assert result.file_texts == []
        mock_load.assert_not_called()

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_reserved_tokens_reduce_available_space(self, mock_load: MagicMock) -> None:
        """Reserved tokens shrink the available window."""
        file_id = str(uuid4())
        uf = _make_user_file(token_count=3000, file_id=file_id)
        # Available = (10000 - 5000) * 0.6 = 3000. Tokens = 3000 → overflow.

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=5000,
            db_session=MagicMock(),
        )

        assert result.use_as_search_filter is True
        mock_load.assert_not_called()

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_image_files_are_extracted(self, mock_load: MagicMock) -> None:
        file_id = str(uuid4())
        uf = _make_user_file(token_count=50, file_id=file_id)
        mock_load.return_value = [
            InMemoryChatFile(
                file_id=file_id,
                content=b"\x89PNG",
                file_type=ChatFileType.IMAGE,
                filename="photo.png",
            )
        ]

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert len(result.image_files) == 1
        assert result.image_files[0].file_id == file_id
        assert result.file_texts == []
        assert result.total_token_count == 50

    @patch("onyx.chat.process_message.DISABLE_VECTOR_DB", True)
    def test_overflow_with_vector_db_disabled_provides_tool_metadata(self) -> None:
        """When vector DB is disabled, overflow produces FileToolMetadata."""
        uf = _make_user_file(token_count=7000, name="bigfile.txt")

        result = extract_context_files(
            user_files=[uf],
            llm_max_context_window=10000,
            reserved_token_count=0,
            db_session=MagicMock(),
        )

        assert result.use_as_search_filter is False
        assert len(result.file_metadata_for_tool) == 1
        assert result.file_metadata_for_tool[0].filename == "bigfile.txt"


# ===========================================================================
# Search filter + search_usage determination
# ===========================================================================


class TestSearchFilterDetermination:
    """Verify that determine_search_params correctly resolves
    search_project_id, search_persona_id, and search_usage based on
    the extraction result and the precedence rule.
    """

    @staticmethod
    def _make_context(
        use_as_search_filter: bool = False,
        file_texts: list[str] | None = None,
        uncapped_token_count: int | None = None,
    ) -> ExtractedContextFiles:
        return ExtractedContextFiles(
            file_texts=file_texts or [],
            image_files=[],
            use_as_search_filter=use_as_search_filter,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=uncapped_token_count,
        )

    def test_custom_persona_files_fit_no_filter(self) -> None:
        """Custom persona, files fit → no search filter, AUTO."""
        result = determine_search_params(
            persona_id=42,
            project_id=99,
            extracted_context_files=self._make_context(
                file_texts=["content"],
                uncapped_token_count=100,
            ),
        )
        assert result.search_project_id is None
        assert result.search_persona_id is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_custom_persona_files_overflow_persona_filter(self) -> None:
        """Custom persona, files overflow → persona_id filter, AUTO."""
        result = determine_search_params(
            persona_id=42,
            project_id=99,
            extracted_context_files=self._make_context(use_as_search_filter=True),
        )
        assert result.search_persona_id == 42
        assert result.search_project_id is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_custom_persona_no_files_no_project_leak(self) -> None:
        """Custom persona (no files) in project → nothing leaks from project."""
        result = determine_search_params(
            persona_id=42,
            project_id=99,
            extracted_context_files=self._make_context(),
        )
        assert result.search_project_id is None
        assert result.search_persona_id is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_default_persona_project_files_fit_disables_search(self) -> None:
        """Default persona, project files fit → DISABLED."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=99,
            extracted_context_files=self._make_context(
                file_texts=["content"],
                uncapped_token_count=100,
            ),
        )
        assert result.search_project_id is None
        assert result.search_usage == SearchToolUsage.DISABLED

    def test_default_persona_project_files_overflow_enables_search(self) -> None:
        """Default persona, project files overflow → ENABLED + project_id filter."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=99,
            extracted_context_files=self._make_context(
                use_as_search_filter=True,
                uncapped_token_count=7000,
            ),
        )
        assert result.search_project_id == 99
        assert result.search_persona_id is None
        assert result.search_usage == SearchToolUsage.ENABLED

    def test_default_persona_no_project_auto(self) -> None:
        """Default persona, no project → AUTO."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=None,
            extracted_context_files=self._make_context(),
        )
        assert result.search_project_id is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_default_persona_project_no_files_disables_search(self) -> None:
        """Default persona in project with no files → DISABLED."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=99,
            extracted_context_files=self._make_context(),
        )
        assert result.search_usage == SearchToolUsage.DISABLED
