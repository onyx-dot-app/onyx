import abc
from collections.abc import Generator
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from pydantic import BaseModel

from onyx.utils.special_types import JSON_ro


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from onyx.tools.models import ToolResponse


OVERRIDE_T = TypeVar("OVERRIDE_T")

TContext = TypeVar("TContext")


class RunContextWrapper(BaseModel, Generic[TContext]):
    """This wraps the context object that you passed to the agent framework query function.

    NOTE: Contexts are not passed to the LLM. They're a way to pass dependencies and data to code
    you implement, like tool functions.
    """

    context: TContext


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
    def get_llm_tool_response(
        self, *args: "ToolResponse"
    ) -> str | list[str | dict[str, Any]]:
        """
        This is the output of the tool which is passed back to the LLM.
        It should be clean and easy to parse for a language model.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_final_result(self, *args: "ToolResponse") -> JSON_ro:
        """
        This is the output of the tool which needs to be stored in the database.
        It will typically contain more information than what is passed back to the LLM
        via the get_llm_tool_response method.
        """
        raise NotImplementedError
