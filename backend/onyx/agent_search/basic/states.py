from typing import TypedDict

from onyx.chat.llm_response_handler import LLMResponseHandlerManager
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.prompt_builder.build import LLMCall
from onyx.llm.chat_llm import LLM

## Update States


## Graph Input State


class BasicInput(TypedDict):
    last_llm_call: LLMCall | None
    llm: LLM
    answer_style_config: AnswerStyleConfig
    response_handler_manager: LLMResponseHandlerManager
    calls: int


## Graph Output State


class BasicOutput(TypedDict):
    pass


class BasicStateUpdate(TypedDict):
    last_llm_call: LLMCall | None
    calls: int


## Graph State


class BasicState(
    BasicInput,
    BasicOutput,
):
    pass
