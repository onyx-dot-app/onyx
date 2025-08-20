import json
from typing import Any, cast, Generator

import requests
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder, default_build_system_message
from onyx.configs.app_configs import LANGFLOW_BASE_URL, LANGFLOW_API_KEY
from onyx.tools.message import ToolCallSummary
from onyx.utils.special_types import JSON_ro
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.models import PreviousMessage
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool_prompts import TOOL_ARG_SYSTEM_PROMPT, TOOL_ARG_USER_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()
LANGFLOW_RESPONSE_SUMMARY_ID = "langflow_response_summary"


class LangflowResponseSummary(BaseModel):
    tool_result: dict
    tool_name: str


class LangflowTool(Tool):
    NAME = "langflow_tool"
    langflow_tool_description = """An API for Langflow"""
    _DISPLAY_NAME = "Langflow"

    def __init__(self, db_session: Session, pipeline_id: str, prompt_config: PromptConfig, llm_config: LLMConfig):
        self.db_session = db_session
        self.pipeline_id = pipeline_id
        self.base_url = LANGFLOW_BASE_URL
        self.prompt_config = prompt_config
        self.llm_config = llm_config

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.langflow_tool_description

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "What to search for",
                        },
                    },
                    "required": ["question"],
                },
            },
        }

    def build_tool_message_content(
            self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        response = cast(LangflowResponseSummary, args[0].response)
        return json.dumps(response.tool_result)

    def get_args_for_non_tool_calling_llm(
            self,
            query: str,
            history: list[PreviousMessage],
            llm: LLM,
            force_run: bool = True,
    ) -> dict[str, Any] | None:

        args_result = llm.invoke(
            [
                SystemMessage(content=TOOL_ARG_SYSTEM_PROMPT),
                HumanMessage(
                    content=TOOL_ARG_USER_PROMPT.format(
                        history=history,
                        query=query,
                        tool_name=self.name,
                        tool_description=self.description,
                        tool_args=self.tool_definition()["function"]["parameters"],
                    )
                ),
            ]
        )
        args_result_str = cast(str, args_result.content)
        logger.info(args_result_str)
        try:
            return json.loads(args_result_str.strip())
        except json.JSONDecodeError:
            pass

        # try removing ```
        try:
            return json.loads(args_result_str.strip("```"))
        except json.JSONDecodeError:
            pass

        # try removing ```json
        try:
            return json.loads(args_result_str.strip("```").strip("json"))
        except json.JSONDecodeError:
            pass

        # pretend like nothing happened if not parse-able
        logger.error(
            f"Failed to parse args for '{self.name}' tool. Received: {args_result_str}"
        )
        return None

    def run(self, **kwargs: Any) -> Generator[ToolResponse, None, None]:
        request_body = {"input_value": kwargs['question']}

        url = self.base_url + f"/api/v1/run/{self.pipeline_id}"
        method = "POST"
        response = requests.request(method, url, json=request_body, headers={"x-api-key": LANGFLOW_API_KEY})
        yield ToolResponse(
            id=LANGFLOW_RESPONSE_SUMMARY_ID,
            response=LangflowResponseSummary(tool_result=response.json(), tool_name=self.name),
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return cast(LangflowResponseSummary, args[0].response).tool_result

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        prompt_builder.update_system_prompt(
            default_build_system_message(self.prompt_config, self.llm_config)
        )
        prompt_builder.update_user_prompt(
            HumanMessage(
                content=build_user_message_for_langflow_tool(
                    query=prompt_builder.get_user_message_content(),
                    tool_name=self.name,
                    *tool_responses
                )
            )
        )

        return prompt_builder


def build_user_message_for_langflow_tool(
        query: str,
        tool_name: str,
        *args: ToolResponse,
) -> str:
    tool_run_summary = cast(LangflowResponseSummary, args[0].response).tool_result
    return f"""
Here's the result from the {tool_name} tool:

{tool_run_summary}

Now respond to the following:

{query}
""".strip()
