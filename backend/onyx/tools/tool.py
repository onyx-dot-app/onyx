import abc
from collections.abc import Generator
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from onyx.utils.special_types import JSON_ro


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from onyx.llm.interfaces import LLM
    from onyx.llm.models import PreviousMessage
    from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
    from onyx.tools.message import ToolCallSummary
    from onyx.tools.models import ToolResponse


OVERRIDE_T = TypeVar("OVERRIDE_T")


class Tool(abc.ABC, Generic[OVERRIDE_T]):
    @property
    @abc.abstractmethod
    def id(self) -> int:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        raise NotImplementedError

    # Added to make tools work better with LLMs in prompts. Should be unique
    # TODO: looks at ways how to best ensure uniqueness.
    # TODO: extra review regarding coding style
    @property
    def llm_name(self) -> str:
        return self.display_name

    @classmethod
    def is_available(cls, db_session: "Session") -> bool:
        """
        Whether this tool is currently available for use given
        the state of the system. Default: available.
        Subclasses may override to perform dynamic checks.

        Args:
            db_session: Database session for tools that need DB access
        """
        return True

    """For LLMs which support explicit tool calling"""

    @abc.abstractmethod
    def tool_definition(self) -> dict:
        raise NotImplementedError

    @abc.abstractmethod
    def build_tool_message_content(
        self, *args: "ToolResponse"
    ) -> str | list[str | dict[str, Any]]:
        raise NotImplementedError

    """For LLMs which do NOT support explicit tool calling"""

    @abc.abstractmethod
    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list["PreviousMessage"],
        llm: "LLM",
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    """Actual execution of the tool"""

    @abc.abstractmethod
    def run(
        self, override_kwargs: OVERRIDE_T | None = None, **llm_kwargs: Any
    ) -> Generator["ToolResponse", None, None]:
        raise NotImplementedError

    @abc.abstractmethod
    def final_result(self, *args: "ToolResponse") -> JSON_ro:
        """
        This is the "final summary" result of the tool.
        It is the result that will be stored in the database.
        """
        raise NotImplementedError

    """Some tools may want to modify the prompt based on the tool call summary and tool responses.
    Default behavior is to continue with just the raw tool call request/result passed to the LLM."""

    @abc.abstractmethod
    def build_next_prompt(
        self,
        prompt_builder: "AnswerPromptBuilder",
        tool_call_summary: "ToolCallSummary",
        tool_responses: list["ToolResponse"],
        using_tool_calling_llm: bool,
    ) -> "AnswerPromptBuilder":
        raise NotImplementedError
