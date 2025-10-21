from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from agents import Agent
from agents import Model
from agents import ModelSettings
from agents import RunContextWrapper
from agents import StopAtTools
from agents import TContext
from agents.tracing.create import trace


@dataclass
class OnyxAgent:
    model: Model
    """The model implementation to use when invoking the LLM.

    By default, if not set, the agent will use the default model configured in
    `agents.models.get_default_model()` (currently "gpt-4.1").
    """

    model_settings: ModelSettings
    """Configures model-specific tuning parameters (e.g. temperature, top_p).
    """

    tool_use_behavior: Literal["run_llm_again"] | StopAtTools = "run_llm_again"
    """
    This lets you configure how tool use is handled.
    - "run_llm_again": The default behavior. Tools are run, and then the LLM receives the results
        and gets to respond.
    """

    task_prompt: str | Callable[[RunContextWrapper[TContext], Agent[TContext]], str]
    """
    This prompt is inserted as a user message to the LLM after every tool call, but it is
    not saved in the conversation history.
    It is useful to help guide behavior at every step of the agent loop.
    """

    def _run_without_middlewares(
        self, input: list[dict], context: TContext | None = None
    ) -> str:
        return "hi"

    def run(self, input: list[dict], context: TContext | None = None) -> str:
        with trace(self.name):
            return self._run_without_middlewares(input, context)
