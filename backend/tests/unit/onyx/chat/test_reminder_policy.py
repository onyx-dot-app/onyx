from typing import Any

from onyx.chat.context_policy import ChatReminderContext, ChatReminderPolicy
from onyx.chat.prompt_utils import select_reminder_text
from onyx.llm.models import ToolResultMessage
from onyx.prompts.chat_prompts import IMAGE_GEN_REMINDER, OPEN_URL_REMINDER
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def test_search_reminder_can_be_removed_without_changing_tool_results() -> None:
    response = ToolResultMessage(
        content="Search results", tool_name=SearchTool.NAME, tool_call_id="search"
    )
    original = response.model_copy(deep=True)
    context = ChatReminderContext(
        ran_image_gen=False,
        has_open_url_tool=False,
        out_of_cycles=False,
        persona_task_prompt="User instructions",
        has_context_documents=False,
    )
    enabled = ChatReminderPolicy()
    disabled = ChatReminderPolicy(enabled=False)
    enabled.after_tools([response])
    disabled.after_tools([response])
    assert enabled.cite_documents
    assert not disabled.cite_documents
    assert enabled.render(context) != disabled.render(context)
    assert disabled.render(context) == "User instructions"
    assert response == original


class TestSelectReminderText:
    """The open_url nudge must be suppressed when the open_url tool is disabled,
    otherwise the model is told to call a tool it doesn't have (confusing
    "open_url is not available" replies)."""

    def _select(self, **overrides: Any) -> str | None:
        kwargs: dict[str, Any] = dict(
            ran_image_gen=False,
            just_ran_web_search=False,
            has_open_url_tool=True,
            out_of_cycles=False,
            persona_task_prompt=None,
            include_citation_reminder=False,
            include_file_reminder=False,
        )
        kwargs.update(overrides)
        return select_reminder_text(**kwargs)

    def test_open_url_reminder_when_tool_available(self) -> None:
        result = self._select(just_ran_web_search=True, has_open_url_tool=True)
        assert result == OPEN_URL_REMINDER

    def test_no_open_url_reminder_when_tool_disabled(self) -> None:
        """Web search ran but open_url is disabled -> fall back, never nudge open_url."""
        result = self._select(just_ran_web_search=True, has_open_url_tool=False)
        assert result != OPEN_URL_REMINDER
        assert result is None  # nothing else to remind about in this scenario

    def test_open_url_reminder_suppressed_on_last_cycle(self) -> None:
        result = self._select(
            just_ran_web_search=True, has_open_url_tool=True, out_of_cycles=True
        )
        assert result != OPEN_URL_REMINDER

    def test_image_gen_reminder_takes_precedence(self) -> None:
        result = self._select(
            ran_image_gen=True, just_ran_web_search=True, has_open_url_tool=True
        )
        assert result == IMAGE_GEN_REMINDER
