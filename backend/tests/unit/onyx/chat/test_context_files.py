"""Tests for the unified context file extraction logic (Phase 5).

Covers:
- resolve_context_user_files: combined project and custom persona files
- extract_context_files: all-or-nothing context window fit check
- Search filter / search_usage determination in the caller
"""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from onyx.chat.models import (
    AvailableFiles,
    ExtractedContextFiles,
    FileToolMetadata,
    SearchParams,
)
from onyx.chat.process_message import (
    _collect_available_file_ids,
    determine_search_params,
    extract_context_files,
    resolve_context_user_files,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.models import ChatMessage, UserFile
from onyx.db.user_file import capture_user_file_metadata
from onyx.file_store.models import ChatFileType, InMemoryChatFile, UserFileMetadata
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
        file_type="text/plain",
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
    @pytest.mark.parametrize("persona_id", [DEFAULT_PERSONA_ID, 42])
    @pytest.mark.parametrize("has_project", [False, True])
    @pytest.mark.parametrize("has_persona_files", [False, True])
    def test_combines_selected_files(
        self, persona_id: int, has_project: bool, has_persona_files: bool
    ) -> None:
        project_file: UserFile = _make_user_file()
        persona_file: UserFile = _make_user_file()
        persona: MagicMock = _make_persona(
            persona_id, [persona_file] if has_persona_files else []
        )
        db_session: MagicMock = MagicMock()
        user_id: UUID = uuid4()
        with patch(
            "onyx.chat.process_message.get_user_files_from_project",
            return_value=[project_file],
        ) as get_files:
            result: list[UserFile] = resolve_context_user_files(
                persona, 99 if has_project else None, user_id, db_session
            )
        expected: list[UserFile] = [project_file] if has_project else []
        if persona_id != DEFAULT_PERSONA_ID and has_persona_files:
            expected.append(persona_file)
        assert result == expected
        if has_project:
            get_files.assert_called_once_with(
                project_id=99, user_id=user_id, db_session=db_session
            )
        else:
            get_files.assert_not_called()

    def test_shared_file_is_selected_once_and_allowlist_keeps_history(self) -> None:
        shared_file: UserFile = _make_user_file()
        persona_file: UserFile = _make_user_file()
        persona: MagicMock = _make_persona(42, [shared_file, persona_file])
        attachment_id: UUID = uuid4()
        history: list[ChatMessage] = [
            ChatMessage(
                files=[
                    {"id": str(attachment_id), "type": ChatFileType.PLAIN_TEXT},
                    {"id": "invalid", "type": ChatFileType.PLAIN_TEXT},
                ]
            )
        ]
        with patch(
            "onyx.chat.process_message.get_user_files_from_project",
            return_value=[shared_file, shared_file],
        ):
            selected: list[UserFile] = resolve_context_user_files(
                persona, 99, uuid4(), MagicMock()
            )
        assert selected == [shared_file, persona_file]
        available: AvailableFiles = _collect_available_file_ids(history, selected)
        assert set(available.user_file_ids) == {shared_file.id, persona_file.id}
        assert available.chat_file_ids == [attachment_id]

    @pytest.mark.parametrize("tokens_per_file", [100, 4000])
    def test_combined_files_share_the_prompt_budget(self, tokens_per_file: int) -> None:
        project_file: UserFile = _make_user_file(tokens_per_file, "project.txt")
        persona_file: UserFile = _make_user_file(tokens_per_file, "agent.txt")
        persona: MagicMock = _make_persona(42, [project_file, persona_file])
        with (
            patch(
                "onyx.chat.process_message.get_user_files_from_project",
                return_value=[project_file],
            ),
            patch(
                "onyx.chat.process_message.load_in_memory_chat_files",
                return_value=[
                    _make_in_memory_file(project_file.file_id, "Project evidence"),
                    _make_in_memory_file(persona_file.file_id, "Agent evidence"),
                ],
            ) as load,
        ):
            selected: list[UserFile] = resolve_context_user_files(
                persona, 99, uuid4(), MagicMock()
            )
            extracted: ExtractedContextFiles = extract_context_files(
                capture_user_file_metadata(selected), 10000, 0
            )
        assert extracted.uncapped_token_count == 2 * tokens_per_file
        if tokens_per_file == 100:
            assert extracted.file_texts == ["Project evidence", "Agent evidence"]
            assert not extracted.use_as_search_filter
            load.assert_called_once()
        else:
            assert extracted.file_texts == []
            assert extracted.use_as_search_filter
            load.assert_not_called()


# ===========================================================================
# extract_context_files
# ===========================================================================


class TestExtractContextFiles:
    """All-or-nothing context window fit check."""

    def test_empty_user_files_returns_empty(self) -> None:
        result = extract_context_files(
            user_files=capture_user_file_metadata([]),
            llm_max_context_window=10000,
            reserved_token_count=0,
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
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
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
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
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
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert result.use_as_search_filter is True

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_just_under_boundary_loads(self, mock_load: MagicMock) -> None:
        """Token count just under the 60% boundary should load files."""
        file_id = str(uuid4())
        uf = _make_user_file(token_count=5999, file_id=file_id)
        mock_load.return_value = [_make_in_memory_file(file_id=file_id, content="data")]

        result = extract_context_files(
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert result.use_as_search_filter is False
        assert result.file_texts == ["data"]

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_multiple_files_aggregate_check(self, mock_load: MagicMock) -> None:
        """Multiple small files that individually fit but collectively overflow."""
        files = [_make_user_file(token_count=2500) for _ in range(3)]
        # 3 * 2500 = 7500 > 6000 threshold

        result = extract_context_files(
            user_files=capture_user_file_metadata(files),
            llm_max_context_window=10000,
            reserved_token_count=0,
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
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=5000,
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
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert len(result.image_files) == 1
        assert result.image_files[0].file_id == file_id
        assert result.file_texts == []
        assert result.total_token_count == 50

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_tool_metadata_file_id_matches_chat_history_file_id(
        self, mock_load: MagicMock
    ) -> None:
        """The file_id in tool metadata (from extract_context_files) and the
        file_id in chat history messages (from build_file_context) must
        agree, otherwise the LLM sees different IDs for the same file across
        turns.

        In production, UserFile.id (UUID PK) differs from UserFile.file_id
        (file-store path). Both pathways should produce the same file_id
        (UserFile.id) for FileReaderTool."""
        from onyx.chat.chat_utils import build_file_context

        user_file_uuid = uuid4()
        file_store_path = f"user_files/{user_file_uuid}/data.csv"

        uf = UserFile(
            id=user_file_uuid,
            file_id=file_store_path,
            name="data.csv",
            token_count=100,
            file_type="text/csv",
        )

        in_memory = InMemoryChatFile(
            file_id=file_store_path,
            content=b"col1,col2\na,b",
            file_type=ChatFileType.TABULAR,
            filename="data.csv",
        )

        mock_load.return_value = [in_memory]

        # Pathway 1: extract_context_files (project/persona context)
        result = extract_context_files(
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )
        assert len(result.file_metadata_for_tool) == 1
        tool_metadata_file_id = result.file_metadata_for_tool[0].file_id

        # Pathway 2: build_file_context (chat history path)
        # In convert_chat_history, tool_file_id comes from
        # file_descriptor["user_file_id"], which is str(UserFile.id)
        ctx = build_file_context(
            tool_file_id=str(user_file_uuid),
            filename="data.csv",
            file_type=ChatFileType.TABULAR,
        )
        chat_history_file_id = ctx.tool_metadata.file_id

        # Both pathways must produce the same ID for the LLM
        assert tool_metadata_file_id == chat_history_file_id, (
            f"File ID mismatch: extract_context_files uses '{tool_metadata_file_id}' "
            f"but build_file_context uses '{chat_history_file_id}'."
        )

    @patch("onyx.chat.process_message.DISABLE_VECTOR_DB", True)
    def test_overflow_with_vector_db_disabled_provides_tool_metadata(self) -> None:
        """When vector DB is disabled, overflow produces FileToolMetadata."""
        uf = _make_user_file(token_count=7000, name="bigfile.txt")

        result = extract_context_files(
            user_files=capture_user_file_metadata([uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert result.use_as_search_filter is False
        assert len(result.file_metadata_for_tool) == 1
        assert result.file_metadata_for_tool[0].filename == "bigfile.txt"

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_metadata_only_files_not_counted_in_aggregate_tokens(
        self, mock_load: MagicMock
    ) -> None:
        """Metadata-only files (TABULAR) should not count toward the token budget."""
        text_file_id = str(uuid4())
        text_uf = _make_user_file(token_count=100, file_id=text_file_id)
        # TABULAR file with large token count — should be excluded from aggregate
        tabular_uf = _make_user_file(
            token_count=50000, name="huge.xlsx", file_id=str(uuid4())
        )
        tabular_uf.file_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        mock_load.return_value = [
            _make_in_memory_file(file_id=text_file_id, content="text content"),
            InMemoryChatFile(
                file_id=str(tabular_uf.id),
                content=b"binary xlsx",
                file_type=ChatFileType.TABULAR,
                filename="huge.xlsx",
            ),
        ]

        result = extract_context_files(
            user_files=capture_user_file_metadata([text_uf, tabular_uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        # Text file fits (100 < 6000), so files should be loaded
        assert result.file_texts == ["text content"]
        # TABULAR file should appear as tool metadata, not in file_texts
        assert len(result.file_metadata_for_tool) == 1
        assert result.file_metadata_for_tool[0].filename == "huge.xlsx"

    @patch("onyx.chat.process_message.load_in_memory_chat_files")
    def test_metadata_only_files_loaded_as_tool_metadata(
        self, mock_load: MagicMock
    ) -> None:
        """When files fit, metadata-only files appear in file_metadata_for_tool."""
        text_file_id = str(uuid4())
        tabular_file_id = str(uuid4())
        text_uf = _make_user_file(token_count=100, file_id=text_file_id)
        tabular_uf = _make_user_file(
            token_count=500, name="data.csv", file_id=tabular_file_id
        )
        tabular_uf.file_type = "text/csv"

        mock_load.return_value = [
            _make_in_memory_file(file_id=text_file_id, content="hello"),
            InMemoryChatFile(
                file_id=tabular_file_id,
                content=b"col1,col2\na,b",
                file_type=ChatFileType.TABULAR,
                filename="data.csv",
            ),
        ]

        result = extract_context_files(
            user_files=capture_user_file_metadata([text_uf, tabular_uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert result.file_texts == ["hello"]
        assert len(result.file_metadata_for_tool) == 1
        assert result.file_metadata_for_tool[0].filename == "data.csv"
        # TABULAR should not appear in file_metadata (that's for citation)
        assert all(m.filename != "data.csv" for m in result.file_metadata)

    def test_overflow_with_vector_db_preserves_metadata_only_tool_metadata(
        self,
    ) -> None:
        """When text files overflow with vector DB enabled, metadata-only files
        should still be exposed via file_metadata_for_tool since they aren't
        in the vector DB and would otherwise be inaccessible."""
        text_uf = _make_user_file(token_count=7000, name="bigfile.txt")
        tabular_uf = _make_user_file(token_count=500, name="data.xlsx")
        tabular_uf.file_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        result = extract_context_files(
            user_files=capture_user_file_metadata([text_uf, tabular_uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        # Text files overflow → search filter enabled
        assert result.use_as_search_filter is True
        assert result.file_texts == []
        # TABULAR file should still be in tool metadata
        assert len(result.file_metadata_for_tool) == 1
        assert result.file_metadata_for_tool[0].filename == "data.xlsx"

    @patch("onyx.chat.process_message.DISABLE_VECTOR_DB", True)
    def test_overflow_no_vector_db_includes_all_files_in_tool_metadata(self) -> None:
        """When vector DB is disabled and files overflow, all files
        (both text and metadata-only) appear in file_metadata_for_tool."""
        text_uf = _make_user_file(token_count=7000, name="bigfile.txt")
        tabular_uf = _make_user_file(token_count=500, name="data.xlsx")
        tabular_uf.file_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        result = extract_context_files(
            user_files=capture_user_file_metadata([text_uf, tabular_uf]),
            llm_max_context_window=10000,
            reserved_token_count=0,
        )

        assert result.use_as_search_filter is False
        assert len(result.file_metadata_for_tool) == 2
        filenames = {m.filename for m in result.file_metadata_for_tool}
        assert filenames == {"bigfile.txt", "data.xlsx"}


# ===========================================================================
# Search filter + search_usage determination
# ===========================================================================


class TestSearchFilterDetermination:
    """Verify that determine_search_params correctly resolves
    project_id_filter, persona_id_filter, and search_usage based on
    the extraction result and both file scopes.
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
        assert result.project_id_filter is None
        assert result.persona_id_filter is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_custom_persona_project_files_overflow_combines_filters(self) -> None:
        """Combined files overflow: search both scopes with the persona policy."""
        result = determine_search_params(
            persona_id=42,
            project_id=99,
            extracted_context_files=self._make_context(use_as_search_filter=True),
        )
        assert result.persona_id_filter == 42
        assert result.project_id_filter == 99
        assert result.search_usage == SearchToolUsage.AUTO

    def test_custom_persona_empty_context_keeps_search_policy(self) -> None:
        """An empty combined context keeps the custom persona search policy."""
        result = determine_search_params(
            persona_id=42,
            project_id=99,
            extracted_context_files=self._make_context(),
        )
        assert result.project_id_filter is None
        assert result.persona_id_filter is None
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
        assert result.project_id_filter is None
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
        assert result.project_id_filter == 99
        assert result.persona_id_filter is None
        assert result.search_usage == SearchToolUsage.ENABLED

    def test_default_persona_no_project_auto(self) -> None:
        """Default persona, no project → AUTO."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=None,
            extracted_context_files=self._make_context(),
        )
        assert result.project_id_filter is None
        assert result.search_usage == SearchToolUsage.AUTO

    def test_default_persona_project_no_files_disables_search(self) -> None:
        """Default persona in project with no files → DISABLED."""
        result = determine_search_params(
            persona_id=DEFAULT_PERSONA_ID,
            project_id=99,
            extracted_context_files=self._make_context(),
        )
        assert result.search_usage == SearchToolUsage.DISABLED

    @pytest.mark.parametrize("persona_id", [DEFAULT_PERSONA_ID, 42])
    @pytest.mark.parametrize("project_id", [None, 99])
    @pytest.mark.parametrize("overflow", [False, True])
    def test_overflow_selects_all_available_scopes(
        self, persona_id: int, project_id: int | None, overflow: bool
    ) -> None:
        result: SearchParams = determine_search_params(
            persona_id=persona_id,
            project_id=project_id,
            extracted_context_files=self._make_context(
                use_as_search_filter=overflow,
                uncapped_token_count=7000 if overflow else 100,
            ),
        )
        assert result.project_id_filter == (project_id if overflow else None)
        assert result.persona_id_filter == (
            persona_id if overflow and persona_id != DEFAULT_PERSONA_ID else None
        )


class TestContextFileStagingFlag:
    """`staged_for_tools` must mirror what actually reaches PythonTool.

    `_load_context_user_files_for_tools` loads only metadata-only files into
    `chat_files_for_tools`, so everything else is listed for the LLM but never
    staged. The out-of-context file notice reads this flag to decide whether it
    may name the python tool; getting it wrong sends the model after bytes the
    tool was never handed.
    """

    def _metadata_for(self, name: str, file_type: str) -> FileToolMetadata:
        from onyx.chat.process_message import _build_tool_metadata

        return _build_tool_metadata(
            UserFileMetadata(
                id=uuid4(),
                file_id=f"user_files/{uuid4()}/{name}",
                name=name,
                token_count=100,
                file_type=file_type,
            )
        )

    def test_tabular_file_is_staged(self) -> None:
        """CSV/XLSX are metadata-only, so they are handed to PythonTool."""
        meta = self._metadata_for("data.csv", "text/csv")
        assert meta.staged_for_tools is True

    def test_non_metadata_only_file_is_not_staged(self) -> None:
        """A PDF is listed for the LLM but never loaded into chat_files_for_tools."""
        meta = self._metadata_for("report.pdf", "application/pdf")
        assert meta.staged_for_tools is False
