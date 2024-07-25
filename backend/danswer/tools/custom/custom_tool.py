import json
from collections.abc import Generator
from typing import Any
from typing import cast

import requests
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from danswer.dynamic_configs.interface import JSON_ro
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.interfaces import LLM
from danswer.tools.custom.custom_tool_prompts import (
    SHOULD_USE_CUSTOM_TOOL_SYSTEM_PROMPT,
)
from danswer.tools.custom.custom_tool_prompts import SHOULD_USE_CUSTOM_TOOL_USER_PROMPT
from danswer.tools.custom.custom_tool_prompts import TOOL_ARG_SYSTEM_PROMPT
from danswer.tools.custom.custom_tool_prompts import TOOL_ARG_USER_PROMPT
from danswer.tools.custom.custom_tool_prompts import USE_TOOL
from danswer.tools.custom.openapi_parsing import MethodSpec
from danswer.tools.custom.openapi_parsing import openapi_to_method_specs
from danswer.tools.custom.openapi_parsing import openapi_to_url
from danswer.tools.custom.openapi_parsing import REQUEST_BODY
from danswer.tools.custom.openapi_parsing import validate_openapi_schema
from danswer.tools.tool import Tool
from danswer.tools.tool import ToolResponse
from danswer.utils.logger import setup_logger

logger = setup_logger()

CUSTOM_TOOL_RESPONSE_ID = "custom_tool_response"


class CustomToolCallSummary(BaseModel):
    tool_name: str
    tool_result: dict


class CustomTool(Tool):
    def __init__(self, method_spec: MethodSpec, base_url: str) -> None:
        self._base_url = base_url
        self._method_spec = method_spec
        self._tool_definition = self._method_spec.to_tool_definition()

        self._name = self._method_spec.name
        self._description = self._method_spec.summary

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def display_name(self) -> str:
        return self._name

    """For LLMs which support explicit tool calling"""

    def tool_definition(self) -> dict:
        return self._tool_definition

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        response = cast(CustomToolCallSummary, args[0].response)
        return json.dumps(response.tool_result)

    """For LLMs which do NOT support explicit tool calling"""

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if not force_run:
            should_use_result = llm.invoke(
                [
                    SystemMessage(content=SHOULD_USE_CUSTOM_TOOL_SYSTEM_PROMPT),
                    HumanMessage(
                        content=SHOULD_USE_CUSTOM_TOOL_USER_PROMPT.format(
                            history=history,
                            query=query,
                            tool_name=self.name,
                            tool_description=self.description,
                        )
                    ),
                ]
            )
            if cast(str, should_use_result.content).strip() != USE_TOOL:
                return None

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
            f"Failed to parse args for '{self.name}' tool. Recieved: {args_result_str}"
        )
        return None

    """Actual execution of the tool"""

    def run(self, **kwargs: Any) -> Generator[ToolResponse, None, None]:
        request_body = kwargs.get(REQUEST_BODY)

        path_params = {}
        for path_param_schema in self._method_spec.get_path_param_schemas():
            path_params[path_param_schema["name"]] = kwargs[path_param_schema["name"]]

        query_params = {}
        for query_param_schema in self._method_spec.get_query_param_schemas():
            if query_param_schema["name"] in kwargs:
                query_params[query_param_schema["name"]] = kwargs[
                    query_param_schema["name"]
                ]

        url = self._method_spec.build_url(self._base_url, path_params, query_params)
        method = self._method_spec.method

        response = requests.request(method, url, json=request_body)

        yield ToolResponse(
            id=CUSTOM_TOOL_RESPONSE_ID,
            response=CustomToolCallSummary(
                tool_name=self._name, tool_result=response.json()
            ),
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return cast(CustomToolCallSummary, args[0].response).tool_result


def build_custom_tools_from_openapi_schema(
    openapi_schema: dict[str, Any]
) -> list[CustomTool]:
    url = openapi_to_url(openapi_schema)
    method_specs = openapi_to_method_specs(openapi_schema)
    return [CustomTool(method_spec, url) for method_spec in method_specs]


if __name__ == "__main__":
    import openai

    openapi_schema = {
        "openapi": "3.0.0",
        "info": {
            "version": "1.0.0",
            "title": "Assistants API",
            "description": "An API for managing assistants",
        },
        "servers": [
            {"url": "http://localhost:8080"},
        ],
        "paths": {
            "/assistant/{assistant_id}": {
                "get": {
                    "summary": "Get a specific Assistant",
                    "operationId": "getAssistant",
                    "parameters": [
                        {
                            "name": "assistant_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                },
                "post": {
                    "summary": "Create a new Assistant",
                    "operationId": "createAssistant",
                    "parameters": [
                        {
                            "name": "assistant_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                },
            }
        },
    }
    validate_openapi_schema(openapi_schema)

    tools = build_custom_tools_from_openapi_schema(openapi_schema)

    openai_client = openai.OpenAI()
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Can you fetch assistant with ID 10"},
        ],
        tools=[tool.tool_definition() for tool in tools],  # type: ignore
    )
    choice = response.choices[0]
    if choice.message.tool_calls:
        print(choice.message.tool_calls)
        for tool_response in tools[0].run(
            **json.loads(choice.message.tool_calls[0].function.arguments)
        ):
            print(tool_response)
