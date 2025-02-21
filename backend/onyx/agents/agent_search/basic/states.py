from typing import TypedDict

from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel

from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate

# States contain values that change over the course of graph execution,
# Config is for values that are set at the start and never change.
# If you are using a value from the config and realize it needs to change,
# you should add it to the state and use/update the version in the state.


## Graph Input State
class BasicInput(BaseModel):
    # Langgraph needs a nonempty input, but we pass in all static
    # data through a RunnableConfig.
    unused: bool = True


## Graph Output State
class BasicOutput(TypedDict):
    tool_call_chunk: AIMessageChunk


## Graph State
class BasicState(
    BasicInput,
    ToolChoiceInput,
    ToolCallUpdate,
    ToolChoiceUpdate,
):
    pass
