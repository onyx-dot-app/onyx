import abc
from collections.abc import Generator
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from onyx.utils.special_types import JSON_ro


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
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

    @abc.abstractmethod
    def tool_definition(self) -> dict:
        """
        This is the full definition of the tool with all of the parameters, settings, etc.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def run(
        self, override_kwargs: OVERRIDE_T | None = None, **llm_kwargs: Any
    ) -> Generator["ToolResponse", None, None]:
        raise NotImplementedError

    @abc.abstractmethod
    def build_tool_message_content(
        self, *args: "ToolResponse"
    ) -> str | list[str | dict[str, Any]]:
        """
        This is the output of the tool which is passed back to the LLM.
        It should be clean and easy to parse for a language model.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def final_result(self, *args: "ToolResponse") -> JSON_ro:
        """
        This is the output of the tool which needs to be stored in the database.
        It will typically contain more information than what is passed back to the LLM
        via the build_tool_message_content method.
        """
        raise NotImplementedError
