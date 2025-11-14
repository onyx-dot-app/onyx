from __future__ import annotations

import abc
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from pydantic import BaseModel


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from onyx.tools.models import ToolResponse


TOverride = TypeVar("TOverride")
TContext = TypeVar("TContext")


class RunContextWrapper(BaseModel, Generic[TContext]):
    """This wraps the context object that you passed to the agent framework query function.

    NOTE: Contexts are not passed to the LLM. They're a way to pass dependencies and data to code
    you implement, like tool functions.
    """

    context: TContext


class Tool(abc.ABC, Generic[TOverride, TContext]):
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
        self,
        # Shared context and dependencies necessary for the tool to run
        # May acrrue bad state/mutations if not used carefully
        # Typically includes things like the packet emitter, redis client, etc.
        run_context: TContext,
        # The run must know its turn and depth because the "Tool" may actually be more of an "Agent" which can call
        # other tools and must pass in this information potentially deeper down.
        turn_index: int,
        depth_index: int,
        # Specific tool override arguments that are not provided by the LLM
        # For example when calling the internal search tool, the original user query is passed along too (but not by the LLM)
        override_kwargs: TOverride,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        raise NotImplementedError
