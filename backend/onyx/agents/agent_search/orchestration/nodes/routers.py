from typing import Literal, cast

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


_ROUTE_ACTION_INSTRUCTIONS = """Analyze the following conversation to determine what action the agent should take next.

The agent can:
- SEARCH: Use the search tool to find relevant information from the knowledge base
- EDIT: Use the document editor tool to modify or create documents
- RESPOND: Provide a final response to the user without using any tools
- REVIEW: Use the document review tool to review the document

Choose SEARCH if:
- The user is asking for information that requires searching the knowledge base
- More context or documents are needed to answer the question
- The user wants to find specific information or documents

Choose EDIT if:
- The user wants to modify, update, or edit an existing document
- The user wants to create new content or documents
- The user is requesting changes to be made to documents

Choose RESPOND if:
- You have sufficient information to answer the user's question
- The user is asking for clarification or explanation of already available information
- No additional tools are needed to provide a complete response

Choose REVIEW if:
- You are instructed to review the document
- The user is asking for feedback of the document or analysis
"""


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["search", "edit", "review", "respond"] = Field(
        description="The action the agent should take: 'search', 'edit', 'review', or 'respond'"
    )


def route_action(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> str:
    """Router node that decides whether the agent should search, edit, or respond."""
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))
    llm = agent_config.tooling.fast_llm
    prompt_builder = agent_config.inputs.prompt_builder
    built_prompt = prompt_builder.build(state_instructions=_ROUTE_ACTION_INSTRUCTIONS)
    stream = llm.stream(
        prompt=built_prompt,
        structured_response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "action_three_way_decision",
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
    return decision.action
