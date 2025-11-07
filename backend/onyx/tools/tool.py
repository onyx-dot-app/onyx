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
        """Should be the name of the tool passed to the LLM as the json field"""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Should be the name of the tool displayed to the user"""
        raise NotImplementedError

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

    # TODO
    # @abc.abstractmethod
    # def llm_facing_result(self, *args: "ToolResponse") -> JSON_ro:
    #     """
    #     This is what the LLM should see as the result of the tool call.
    #     """
    #     raise NotImplementedError
