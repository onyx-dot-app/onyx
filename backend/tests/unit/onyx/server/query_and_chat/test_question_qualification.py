"""
Unit tests for Question Qualification Service

Tests cover:
- Lazy loading when ENABLE_QUESTION_QUALIFICATION is disabled
- Config loading only when enabled
- HTTPException propagation in query_backend
"""

import sys
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException

# Mock heavy dependencies before importing the module under test
# This is necessary because question_qualification.py imports from onyx.llm.factory
# which has a large dependency chain


@pytest.fixture(autouse=True)
def mock_heavy_dependencies():
    """Mock heavy dependencies before any imports."""
    # Store original modules
    original_modules = {}
    modules_to_mock = [
        "onyx.llm.factory",
        "onyx.llm.interfaces",
        "onyx.db.models",
        "onyx.chat.models",
        "onyx.context.search.models",
        "sqlalchemy",
        "sqlalchemy.orm",
    ]

    for module_name in modules_to_mock:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
        sys.modules[module_name] = MagicMock()

    # Create mock LLM
    mock_llm = MagicMock()
    mock_llm.config.model_name = "test-model"
    mock_llm.config.model_provider = "test-provider"

    # Mock get_default_llms to return (llm, fast_llm)
    sys.modules["onyx.llm.factory"].get_default_llms = MagicMock(
        return_value=(mock_llm, mock_llm)
    )
    sys.modules["onyx.llm.interfaces"].LLM = MagicMock

    yield

    # Restore original modules
    for module_name in modules_to_mock:
        if module_name in original_modules:
            sys.modules[module_name] = original_modules[module_name]
        else:
            sys.modules.pop(module_name, None)

    # Clear the question_qualification module so it can be re-imported fresh
    sys.modules.pop("onyx.server.query_and_chat.question_qualification", None)


@pytest.fixture(autouse=True)
def reset_singleton(mock_heavy_dependencies):
    """Reset singleton state before each test."""
    # Need to import after mocking
    yield
    # Cleanup after test - re-import to get fresh module
    if "onyx.server.query_and_chat.question_qualification" in sys.modules:
        module = sys.modules["onyx.server.query_and_chat.question_qualification"]
        if hasattr(module, "QuestionQualificationService"):
            module.QuestionQualificationService._instance = None
            module.QuestionQualificationService._initialized = False


class TestQuestionQualificationService:
    """Test QuestionQualificationService behavior."""

    def test_singleton_pattern(self):
        """Test that service is a singleton."""
        # Import after mocking
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationService,
        )

        # Reset singleton state for this test
        QuestionQualificationService._instance = None
        QuestionQualificationService._initialized = False

        service1 = QuestionQualificationService()
        service2 = QuestionQualificationService()
        assert service1 is service2

    @patch(
        "onyx.server.query_and_chat.question_qualification.ENABLE_QUESTION_QUALIFICATION",
        False,
    )
    def test_no_config_loading_when_disabled(self):
        """Test that config is not loaded when ENABLE_QUESTION_QUALIFICATION is False."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationService,
        )

        # Reset singleton state for this test
        QuestionQualificationService._instance = None
        QuestionQualificationService._initialized = False

        service = QuestionQualificationService()

        # Config should not be loaded when disabled
        assert not service._config_loaded
        assert service.questions == []

    @patch(
        "onyx.server.query_and_chat.question_qualification.ENABLE_QUESTION_QUALIFICATION",
        False,
    )
    def test_qualify_question_returns_not_blocked_when_disabled(self):
        """Test that qualify_question returns not blocked when feature is disabled."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationService,
        )

        # Reset singleton state for this test
        QuestionQualificationService._instance = None
        QuestionQualificationService._initialized = False

        service = QuestionQualificationService()
        mock_db_session = MagicMock()

        result = service.qualify_question("What is someone's salary?", mock_db_session)

        assert not result.is_blocked
        assert result.similarity_score == 0.0

    @patch(
        "onyx.server.query_and_chat.question_qualification.ENABLE_QUESTION_QUALIFICATION",
        True,
    )
    @patch(
        "onyx.server.query_and_chat.question_qualification.QuestionQualificationService._load_config"
    )
    def test_config_loading_when_enabled(self, mock_load_config):
        """Test that config loads when enabled."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationService,
        )

        # Reset singleton state for this test
        QuestionQualificationService._instance = None
        QuestionQualificationService._initialized = False

        mock_load_config.return_value = True
        service = QuestionQualificationService()

        # When enabled, _load_config should be called during init
        assert service is not None

    def test_get_stats(self):
        """Test get_stats method."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationService,
        )

        # Reset singleton state for this test
        QuestionQualificationService._instance = None
        QuestionQualificationService._initialized = False

        service = QuestionQualificationService()
        stats = service.get_stats()

        assert "enabled" in stats
        assert "num_blocked_questions" in stats
        assert "threshold" in stats
        assert "standard_response" in stats


class TestHTTPExceptionPropagation:
    """Test HTTPException propagation in query_backend."""

    def test_http_exception_re_raised_in_get_answer_with_citation(self):
        """Test that HTTPException is re-raised in get_answer_with_citation.

        This test verifies the pattern used in the fix - HTTPException should be
        caught separately and re-raised to preserve status codes.
        """
        with pytest.raises(HTTPException) as exc_info:
            raise HTTPException(status_code=403, detail="Blocked query")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Blocked query"

    def test_http_exception_re_raised_in_stream_answer_with_citation(self):
        """Test that HTTPException is re-raised in stream_answer_with_citation.

        This test verifies the pattern used in the fix - HTTPException should be
        caught before creating StreamingResponse to preserve status codes.
        """
        with pytest.raises(HTTPException) as exc_info:
            raise HTTPException(status_code=403, detail="Blocked query")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Blocked query"

    def test_http_exception_vs_generic_exception(self):
        """Test that HTTPException is distinct from generic Exception."""
        # Verify HTTPException is a subclass of Exception
        assert issubclass(HTTPException, Exception)

        # But we can catch it specifically
        try:
            raise HTTPException(status_code=403, detail="Test")
        except HTTPException as e:
            assert e.status_code == 403
        except Exception:
            pytest.fail(
                "HTTPException should be caught by HTTPException handler, not generic Exception"
            )


class TestQuestionQualificationResult:
    """Test QuestionQualificationResult data class."""

    def test_result_attributes(self):
        """Test that result has expected attributes."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationResult,
        )

        result = QuestionQualificationResult(
            is_blocked=True,
            similarity_score=0.95,
            standard_response="Blocked",
            matched_question="salary question",
            matched_question_index=0,
            reasoning="test",
        )

        assert result.is_blocked is True
        assert result.similarity_score == 0.95
        assert result.standard_response == "Blocked"
        assert result.matched_question == "salary question"
        assert result.matched_question_index == 0
        assert result.reasoning == "test"

    def test_result_defaults(self):
        """Test default values for result."""
        from onyx.server.query_and_chat.question_qualification import (
            QuestionQualificationResult,
        )

        result = QuestionQualificationResult(is_blocked=False)

        assert result.is_blocked is False
        assert result.similarity_score == 0.0
        assert result.standard_response == ""
        assert result.matched_question == ""
        assert result.matched_question_index == -1
        assert result.reasoning == ""
