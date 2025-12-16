from __future__ import annotations

import abc
from typing import Any
from typing import Generic
from typing import TYPE_CHECKING
from typing import TypeVar

from onyx.chat.emitter import Emitter


if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from onyx.tools.models import ToolResponse


TOverride = TypeVar("TOverride")


class Tool(abc.ABC, Generic[TOverride]):
    def __init__(self, emitter: Emitter | None = None):
        """Initialize tool with optional emitter. Emitter can be set later via set_emitter()."""
        self._emitter = emitter

    @property
    def emitter(self) -> Emitter:
        """Get the emitter. Raises if not set."""
        if self._emitter is None:
            raise ValueError(
                f"Emitter not set on tool {self.name}. Call set_emitter() first."
            )
        return self._emitter

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
    def emit_start(self, turn_index: int, tab_index: int = 0) -> None:
        """
        Emit the start packet for this tool. Each tool implementation should
        emit its specific start packet type.

        Args:
            turn_index: The turn index for this tool execution
            tab_index: The tab index for parallel tool calls
        """
        raise NotImplementedError

    @abc.abstractmethod
    def run(
        self,
        # The run must know its turn because the "Tool" may actually be more of an "Agent" which can call
        # other tools and must pass in this information potentially deeper down.
        turn_index: int,
        # Specific tool override arguments that are not provided by the LLM
        # For example when calling the internal search tool, the original user query is passed along too (but not by the LLM)
        override_kwargs: TOverride,
        # Tab index for parallel tool calls (default 0 for single tool calls)
        tab_index: int = 0,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        raise NotImplementedError
