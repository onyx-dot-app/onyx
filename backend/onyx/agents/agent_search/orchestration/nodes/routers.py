from typing import cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter
from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.document_chat.states import DocumentChatState
from onyx.agents.agent_search.models import GraphConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ROUTE_THINKING_INSTRUCTIONS = """Analyze the following conversation and user query to determine if the agent should think before responding.

The agent should THINK first if:
- The query is complex and requires multi-step reasoning
- The query involves analysis, comparison, or evaluation
- The query requires synthesizing information from multiple sources
- The query involves mathematical calculations or logical deduction
- The query is ambiguous and needs clarification of intent

The agent can RESPOND directly if:
- The query is straightforward and factual
- The query is a simple question with a clear answer
- The query is a greeting or casual conversation
- The query asks for basic information retrieval
- The query is asking for a simple explanation or definition

Based on this analysis, should the agent think before responding?"""


class ThinkingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_think: bool = Field(
        description="Whether the agent should think before responding"
    )


def route_thinking(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> bool:
    """
    Router node that decides whether the agent should think before responding.
    """
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))
    llm = agent_config.tooling.fast_llm
    prompt_builder = agent_config.inputs.prompt_builder
    built_prompt = prompt_builder.build(state_instructions=_ROUTE_THINKING_INSTRUCTIONS)
    stream = llm.stream(
        prompt=built_prompt,
        structured_response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "thinking_decision",
                "schema": ThinkingDecision.model_json_schema(),
                "strict": True,
            },
        },
    )
    response_chunk = process_llm_stream(
        stream, should_stream_answer=False, writer=writer, return_text_content=True
    )
    assert isinstance(response_chunk.content, str)
    decision = ThinkingDecision.model_validate_json(response_chunk.content)
    return decision.should_think


_ROUTE_TOOL_USE_INSTRUCTIONS = """Analyze the following conversation to determine whether the agent needs to use a tool to respond to the user."""


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_act: bool = Field(
        description="Whether the agent should act (use a tool) or respond to the user"
    )


def route_action(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> bool:
    """Router node that decides whether the agent should use a tool to respond to the user."""
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))
    llm = agent_config.tooling.fast_llm
    prompt_builder = agent_config.inputs.prompt_builder
    built_prompt = prompt_builder.build(state_instructions=_ROUTE_TOOL_USE_INSTRUCTIONS)
    stream = llm.stream(
        prompt=built_prompt,
        structured_response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "action_decision",
                "schema": ActionDecision.model_json_schema(),
                "strict": True,
            },
        },
    )
    response_chunk = process_llm_stream(
        stream, should_stream_answer=False, writer=writer, return_text_content=True
    )
    assert isinstance(response_chunk.content, str)
    decision = ActionDecision.model_validate_json(response_chunk.content)
    return decision.should_act
