from typing import TypedDict

from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection


# States contain values that change over the course of graph execution,
# Config is for values that are set at the start and never change.
# If you are using a value from the config and realize it needs to change,
# you should add it to the state and use/update the version in the state.


## Graph Input State
class BasicInput(BaseModel):
    # Langgraph needs a nonempty input, but we pass in all static
    # data through a RunnableConfig.
    unused: bool = True
    query_override: str | None = None


## Graph Output State
class BasicOutput(TypedDict):
    tool_call_chunk: AIMessageChunk
    full_answer: str | None
    cited_references: list[InferenceSection] | None
    retrieved_documents: list[LlmDoc] | None


## Graph State
class BasicState(
    BasicInput,
    ToolChoiceInput,
    ToolCallUpdate,
    ToolChoiceUpdate,
):
    pass
