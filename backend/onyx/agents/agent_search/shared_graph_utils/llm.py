import re
from datetime import datetime
from typing import cast
from typing import Literal
from typing import Type
from typing import TypeVar

from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import HumanMessage
from langgraph.types import StreamWriter
from litellm import get_supported_openai_params
from litellm import supports_response_schema
from pydantic import BaseModel

from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.utils.threadpool_concurrency import run_with_timeout


SchemaType = TypeVar("SchemaType", bound=BaseModel)

# match ```json{...}``` or ```{...}```
JSON_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def stream_llm_answer(
    llm: LLM,
    prompt: LanguageModelInput,
    event_name: str,
    writer: StreamWriter,
    agent_answer_level: int,
    agent_answer_question_num: int,
    agent_answer_type: Literal["agent_level_answer", "agent_sub_answer"],
    timeout_override: int | None = None,
    max_tokens: int | None = None,
) -> tuple[list[str], list[float]]:
    """Stream the initial answer from the LLM.

    Args:
        llm: The LLM to use.
        prompt: The prompt to use.
        event_name: The name of the event to write.
        writer: The writer to write to.
        agent_answer_level: The level of the agent answer.
        agent_answer_question_num: The question number within the level.
        agent_answer_type: The type of answer ("agent_level_answer" or "agent_sub_answer").
        timeout_override: The LLM timeout to use.
        max_tokens: The LLM max tokens to use.

    Returns:
        A tuple of the response and the dispatch timings.
    """
    response: list[str] = []
    dispatch_timings: list[float] = []

    for message in llm.stream(
        prompt, timeout_override=timeout_override, max_tokens=max_tokens
    ):
        # TODO: in principle, the answer here COULD contain images, but we don't support that yet
        content = message.content
        if not isinstance(content, str):
            raise ValueError(
                f"Expected content to be a string, but got {type(content)}"
            )

        start_stream_token = datetime.now()
        write_custom_event(
            event_name,
            AgentAnswerPiece(
                answer_piece=content,
                level=agent_answer_level,
                level_question_num=agent_answer_question_num,
                answer_type=agent_answer_type,
            ),
            writer,
        )
        end_stream_token = datetime.now()

        dispatch_timings.append((end_stream_token - start_stream_token).microseconds)
        response.append(content)

    return response, dispatch_timings


def invoke_llm_json(
    llm: LLM,
    prompt: LanguageModelInput,
    schema: Type[SchemaType],
    tools: list[dict] | None = None,
    tool_choice: ToolChoiceOptions | None = None,
    timeout_override: int | None = None,
    max_tokens: int | None = None,
) -> SchemaType:
    """
    Invoke an LLM, forcing it to respond in a specified JSON format if possible,
    and return an object of that schema.
    """

    # check if the model supports response_format: json_schema
    supports_json = "response_format" in (
        get_supported_openai_params(llm.config.model_name, llm.config.model_provider)
        or []
    ) and supports_response_schema(llm.config.model_name, llm.config.model_provider)

    response_content = str(
        llm.invoke(
            prompt,
            tools=tools,
            tool_choice=tool_choice,
            timeout_override=timeout_override,
            max_tokens=max_tokens,
            **cast(
                dict, {"structured_response_format": schema} if supports_json else {}
            ),
        ).content
    )

    if not supports_json:
        # remove newlines as they often lead to json decoding errors
        response_content = response_content.replace("\n", " ")
        # hope the prompt is structured in a way a json is outputted...
        json_block_match = JSON_PATTERN.search(response_content)
        if json_block_match:
            response_content = json_block_match.group(1)
        else:
            first_bracket = response_content.find("{")
            last_bracket = response_content.rfind("}")
            response_content = response_content[first_bracket : last_bracket + 1]

    return schema.model_validate_json(response_content)


def get_answer_from_llm(
    llm: LLM,
    prompt: str,
    timeout: int = 25,
    timeout_override: int = 5,
    max_tokens: int = 500,
    stream: bool = False,
    writer: StreamWriter = lambda _: None,
    agent_answer_level: int = 0,
    agent_answer_question_num: int = 0,
    agent_answer_type: Literal[
        "agent_sub_answer", "agent_level_answer"
    ] = "agent_level_answer",
    json_string_flag: bool = False,
) -> str:
    msg = [
        HumanMessage(
            content=prompt,
        )
    ]

    if stream:
        # TODO - adjust for new UI. This is currently not working for current UI/Basic Search
        stream_response, _ = run_with_timeout(
            timeout,
            lambda: stream_llm_answer(
                llm=llm,
                prompt=msg,
                event_name="sub_answers",
                writer=writer,
                agent_answer_level=agent_answer_level,
                agent_answer_question_num=agent_answer_question_num,
                agent_answer_type=agent_answer_type,
                timeout_override=timeout_override,
                max_tokens=max_tokens,
            ),
        )
        content = "".join(stream_response)
    else:
        llm_response = run_with_timeout(
            timeout,
            llm.invoke,
            prompt=msg,
            timeout_override=timeout_override,
            max_tokens=max_tokens,
        )
        content = str(llm_response.content)

    cleaned_response = content
    if json_string_flag:
        cleaned_response = (
            str(content).replace("```json\n", "").replace("\n```", "").replace("\n", "")
        )
        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]

    return cleaned_response
