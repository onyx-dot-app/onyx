"""Tests for chat_utils.py, specifically get_custom_agent_prompt."""

from io import BytesIO
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.chat.chat_utils import _build_tool_call_response_history_message
from onyx.chat.chat_utils import _get_or_extract_plaintext
from onyx.chat.chat_utils import get_custom_agent_prompt
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE


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

    def test_custom_persona_none_system_prompt(self) -> None:
        """Test that custom persona with None system_prompt returns None."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt=None,
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

    def test_custom_persona_replace_base_in_project(self) -> None:
        """Test that custom persona with replace_base_system_prompt=True in a project still returns None."""
        persona = self._create_mock_persona(
            persona_id=1,
            system_prompt="Custom system prompt",
            replace_base_system_prompt=True,
        )
        project = self._create_mock_project(instructions="Project instructions")
        chat_session = self._create_mock_chat_session(project=project)

        result = get_custom_agent_prompt(persona, chat_session)

        # Should return None because replace_base_system_prompt=True
        assert result is None


class TestBuildToolCallResponseHistoryMessage:
    def test_image_tool_uses_generated_images(self) -> None:
        message = _build_tool_call_response_history_message(
            tool_name="generate_image",
            generated_images=[{"file_id": "img-1", "revised_prompt": "p1"}],
            tool_call_response=None,
        )
        assert message == '[{"file_id": "img-1", "revised_prompt": "p1"}]'

    def test_non_image_tool_uses_placeholder(self) -> None:
        message = _build_tool_call_response_history_message(
            tool_name="web_search",
            generated_images=None,
            tool_call_response='{"raw":"value"}',
        )
        assert message == TOOL_CALL_RESPONSE_CROSS_MESSAGE


class TestGetOrExtractPlaintext:
    """Tests for the plaintext extraction cache used by chat file loading."""

    def test_cache_hit_skips_extraction(self) -> None:
        file_store = MagicMock()
        file_store.read_file.return_value = BytesIO(b"cached text")
        extract_fn = MagicMock(return_value="should not be called")

        with (
            patch(
                "onyx.chat.chat_utils.get_default_file_store",
                return_value=file_store,
            ),
            patch("onyx.chat.chat_utils.store_plaintext") as store_plaintext,
        ):
            result = _get_or_extract_plaintext("file-1", extract_fn)

        assert result == "cached text"
        extract_fn.assert_not_called()
        store_plaintext.assert_not_called()

    def test_cache_miss_stores_extracted_text(self) -> None:
        file_store = MagicMock()
        file_store.read_file.side_effect = RuntimeError("not in store")
        extract_fn = MagicMock(return_value="extracted text")

        with (
            patch(
                "onyx.chat.chat_utils.get_default_file_store",
                return_value=file_store,
            ),
            patch("onyx.chat.chat_utils.store_plaintext") as store_plaintext,
        ):
            result = _get_or_extract_plaintext("file-2", extract_fn)

        assert result == "extracted text"
        extract_fn.assert_called_once()
        store_plaintext.assert_called_once_with("file-2", "extracted text")

    def test_cache_miss_caches_empty_extraction(self) -> None:
        """Files extract_file_text cannot process (e.g. .zip) return "".
        We must still cache that result so we don't re-fetch the file from
        object storage on every subsequent chat turn.
        """
        file_store = MagicMock()
        file_store.read_file.side_effect = RuntimeError("not in store")
        extract_fn = MagicMock(return_value="")

        with (
            patch(
                "onyx.chat.chat_utils.get_default_file_store",
                return_value=file_store,
            ),
            patch("onyx.chat.chat_utils.store_plaintext") as store_plaintext,
        ):
            result = _get_or_extract_plaintext("file-3", extract_fn)

        assert result == ""
        extract_fn.assert_called_once()
        store_plaintext.assert_called_once_with("file-3", "")
