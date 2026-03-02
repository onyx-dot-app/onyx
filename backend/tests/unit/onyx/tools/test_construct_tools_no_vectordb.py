"""Tests for tool construction when DISABLE_VECTOR_DB is True.

Verifies that:
- SearchTool.is_available() returns False when vector DB is disabled
- OpenURLTool.is_available() returns False when vector DB is disabled
- The force-add SearchTool block is suppressed when DISABLE_VECTOR_DB
- FileReaderTool.is_available() returns True when vector DB is disabled
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool

APP_CONFIGS_MODULE = "onyx.configs.app_configs"
FILE_READER_MODULE = "onyx.tools.tool_implementations.file_reader.file_reader_tool"


# ------------------------------------------------------------------
# SearchTool.is_available()
# ------------------------------------------------------------------


class TestSearchToolAvailability:
    @patch(f"{APP_CONFIGS_MODULE}.DISABLE_VECTOR_DB", True)
    def test_unavailable_when_vector_db_disabled(self) -> None:
        from onyx.tools.tool_implementations.search.search_tool import SearchTool

        assert SearchTool.is_available(MagicMock()) is False

    @patch("onyx.db.connector.check_user_files_exist", return_value=True)
    @patch(
        "onyx.tools.tool_implementations.search.search_tool.check_federated_connectors_exist",
        return_value=False,
    )
    @patch(
        "onyx.tools.tool_implementations.search.search_tool.check_connectors_exist",
        return_value=False,
    )
    @patch(f"{APP_CONFIGS_MODULE}.DISABLE_VECTOR_DB", False)
    def test_available_when_vector_db_enabled_and_files_exist(
        self,
        mock_connectors: MagicMock,  # noqa: ARG002
        mock_federated: MagicMock,  # noqa: ARG002
        mock_user_files: MagicMock,  # noqa: ARG002
    ) -> None:
        from onyx.tools.tool_implementations.search.search_tool import SearchTool

        assert SearchTool.is_available(MagicMock()) is True


# ------------------------------------------------------------------
# OpenURLTool.is_available()
# ------------------------------------------------------------------


class TestOpenURLToolAvailability:
    @patch(f"{APP_CONFIGS_MODULE}.DISABLE_VECTOR_DB", True)
    def test_unavailable_when_vector_db_disabled(self) -> None:
        from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool

        assert OpenURLTool.is_available(MagicMock()) is False

    @patch(f"{APP_CONFIGS_MODULE}.DISABLE_VECTOR_DB", False)
    def test_available_when_vector_db_enabled(self) -> None:
        from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool

        assert OpenURLTool.is_available(MagicMock()) is True


# ------------------------------------------------------------------
# FileReaderTool.is_available()
# ------------------------------------------------------------------


class TestFileReaderToolAvailability:
    @patch(f"{FILE_READER_MODULE}.DISABLE_VECTOR_DB", True)
    def test_available_when_vector_db_disabled(self) -> None:
        assert FileReaderTool.is_available(MagicMock()) is True

    @patch(f"{FILE_READER_MODULE}.DISABLE_VECTOR_DB", False)
    def test_unavailable_when_vector_db_enabled(self) -> None:
        assert FileReaderTool.is_available(MagicMock()) is False


# ------------------------------------------------------------------
# Force-add SearchTool suppression
# ------------------------------------------------------------------


class TestForceAddSearchToolGuard:
    def test_force_add_block_checks_disable_vector_db(self) -> None:
        """The force-add SearchTool block in construct_tools should include
        `not DISABLE_VECTOR_DB` so that forced search is also suppressed
        without a vector DB."""
        import inspect

        from onyx.tools.tool_constructor import construct_tools

        source = inspect.getsource(construct_tools)
        assert "DISABLE_VECTOR_DB" in source, (
            "construct_tools should reference DISABLE_VECTOR_DB "
            "to suppress force-adding SearchTool"
        )


# ------------------------------------------------------------------
# Persona API — _validate_vector_db_knowledge
# ------------------------------------------------------------------


class TestValidateVectorDbKnowledge:
    @patch(
        "onyx.server.features.persona.api.DISABLE_VECTOR_DB",
        True,
    )
    def test_rejects_document_set_ids(self) -> None:
        from fastapi import HTTPException

        from onyx.server.features.persona.api import _validate_vector_db_knowledge

        request = MagicMock()
        request.document_set_ids = [1]
        request.hierarchy_node_ids = []
        request.document_ids = []

        with __import__("pytest").raises(HTTPException) as exc_info:
            _validate_vector_db_knowledge(request)
        assert exc_info.value.status_code == 400
        assert "document sets" in exc_info.value.detail

    @patch(
        "onyx.server.features.persona.api.DISABLE_VECTOR_DB",
        True,
    )
    def test_rejects_hierarchy_node_ids(self) -> None:
        from fastapi import HTTPException

        from onyx.server.features.persona.api import _validate_vector_db_knowledge

        request = MagicMock()
        request.document_set_ids = []
        request.hierarchy_node_ids = [1]
        request.document_ids = []

        with __import__("pytest").raises(HTTPException) as exc_info:
            _validate_vector_db_knowledge(request)
        assert exc_info.value.status_code == 400
        assert "hierarchy nodes" in exc_info.value.detail

    @patch(
        "onyx.server.features.persona.api.DISABLE_VECTOR_DB",
        True,
    )
    def test_rejects_document_ids(self) -> None:
        from fastapi import HTTPException

        from onyx.server.features.persona.api import _validate_vector_db_knowledge

        request = MagicMock()
        request.document_set_ids = []
        request.hierarchy_node_ids = []
        request.document_ids = ["doc-abc"]

        with __import__("pytest").raises(HTTPException) as exc_info:
            _validate_vector_db_knowledge(request)
        assert exc_info.value.status_code == 400
        assert "documents" in exc_info.value.detail

    @patch(
        "onyx.server.features.persona.api.DISABLE_VECTOR_DB",
        True,
    )
    def test_allows_user_files_only(self) -> None:
        from onyx.server.features.persona.api import _validate_vector_db_knowledge

        request = MagicMock()
        request.document_set_ids = []
        request.hierarchy_node_ids = []
        request.document_ids = []

        _validate_vector_db_knowledge(request)

    @patch(
        "onyx.server.features.persona.api.DISABLE_VECTOR_DB",
        False,
    )
    def test_allows_everything_when_vector_db_enabled(self) -> None:
        from onyx.server.features.persona.api import _validate_vector_db_knowledge

        request = MagicMock()
        request.document_set_ids = [1, 2]
        request.hierarchy_node_ids = [3]
        request.document_ids = ["doc-x"]

        _validate_vector_db_knowledge(request)
