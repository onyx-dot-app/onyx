import csv
import json
import uuid
from collections.abc import Generator
from io import BytesIO
from io import StringIO
from typing import Any
from typing import cast
from typing import Dict
from typing import List

import requests
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import BaseModel
from requests import JSONDecodeError

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.base_tool import BaseTool
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import CHAT_SESSION_ID_PLACEHOLDER
from onyx.tools.models import DynamicSchemaInfo
from onyx.tools.models import MESSAGE_ID_PLACEHOLDER
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.custom.custom_tool_prompts import (
    SHOULD_USE_CUSTOM_TOOL_SYSTEM_PROMPT,
)
from onyx.tools.tool_implementations.custom.custom_tool_prompts import (
    SHOULD_USE_CUSTOM_TOOL_USER_PROMPT,
)
from onyx.tools.tool_implementations.custom.custom_tool_prompts import (
    TOOL_ARG_SYSTEM_PROMPT,
)
from onyx.tools.tool_implementations.custom.custom_tool_prompts import (
    TOOL_ARG_USER_PROMPT,
)
from onyx.tools.tool_implementations.custom.custom_tool_prompts import USE_TOOL
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import openapi_to_url
from onyx.tools.tool_implementations.custom.openapi_parsing import REQUEST_BODY
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    validate_openapi_schema,
)
from onyx.tools.tool_implementations.custom.prompt import (
    build_custom_image_generation_user_prompt,
)
from onyx.utils.headers import header_list_to_header_dict
from onyx.utils.headers import HeaderItemDict
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

CUSTOM_TOOL_RESPONSE_ID = "custom_tool_response"


class CustomToolUserFileSnapshot(BaseModel):
    file_ids: List[str]  # References to saved images or CSVs


class CustomToolCallSummary(BaseModel):
    tool_name: str
    response_type: str  # e.g., 'json', 'image', 'csv', 'graph'
    tool_result: Any  # The response data


# override_kwargs is not supported for custom tools
class CustomTool(BaseTool):
    def __init__(
        self,
        id: int,
        method_spec: MethodSpec,
        base_url: str,
        custom_headers: list[HeaderItemDict] | None = None,
        user_oauth_token: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._method_spec = method_spec
        self._tool_definition = self._method_spec.to_tool_definition()
        self._user_oauth_token = user_oauth_token
        self._id = id

        self._name = self._method_spec.name
        self._description = self._method_spec.summary
        self.headers = (
            header_list_to_header_dict(custom_headers) if custom_headers else {}
        )

        # Check for both Authorization header and OAuth token
        has_auth_header = any(
            key.lower() == "authorization" for key in self.headers.keys()
        )
        if has_auth_header and self._user_oauth_token:
            logger.warning(
                f"Tool '{self._name}' has both an Authorization "
                "header and OAuth token set. This is likely a configuration "
                "error as the OAuth token will override the custom header."
            )

        if self._user_oauth_token:
            self.headers["Authorization"] = f"Bearer {self._user_oauth_token}"

    @property
    def id(self) -> int:
        return self._id

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

        if response.response_type == "image" or response.response_type == "csv":
            image_response = cast(CustomToolUserFileSnapshot, response.tool_result)
            return json.dumps({"file_ids": image_response.file_ids})

        # For JSON or other responses, return as-is
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
            f"Failed to parse args for '{self.name}' tool. Received: {args_result_str}"
        )
        return None

    def _save_and_get_file_references(
        self, file_content: bytes | str, content_type: str
    ) -> List[str]:
        file_store = get_default_file_store()

        file_id = str(uuid.uuid4())

        # Handle both binary and text content
        if isinstance(file_content, str):
            content = BytesIO(file_content.encode())
        else:
            content = BytesIO(file_content)

        file_store.save_file(
            file_id=file_id,
            content=content,
            display_name=file_id,
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type=content_type,
            file_metadata={
                "content_type": content_type,
            },
        )

        return [file_id]

    def _parse_csv(self, csv_text: str) -> List[Dict[str, Any]]:
        csv_file = StringIO(csv_text)
        reader = csv.DictReader(csv_file)
        return [row for row in reader]

    """Actual execution of the tool"""

    def run(
        self, override_kwargs: dict[str, Any] | None = None, **kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
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

        response = requests.request(
            method, url, json=request_body, headers=self.headers
        )
        content_type = response.headers.get("Content-Type", "")

        tool_result: Any
        response_type: str
        if "text/csv" in content_type:
            file_ids = self._save_and_get_file_references(
                response.content, content_type
            )
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "csv"

        elif "image/" in content_type:
            file_ids = self._save_and_get_file_references(
                response.content, content_type
            )
            tool_result = CustomToolUserFileSnapshot(file_ids=file_ids)
            response_type = "image"

        else:
            try:
                tool_result = response.json()
                response_type = "json"
            except JSONDecodeError:
                logger.exception(
                    f"Failed to parse response as JSON for tool '{self._name}'"
                )
                tool_result = response.text
                response_type = "text"

        logger.info(
            f"Returning tool response for {self._name} with type {response_type}"
        )

        yield ToolResponse(
            id=CUSTOM_TOOL_RESPONSE_ID,
            response=CustomToolCallSummary(
                tool_name=self._name,
                response_type=response_type,
                tool_result=tool_result,
            ),
        )

    def build_next_prompt(
        self,
        prompt_builder: AnswerPromptBuilder,
        tool_call_summary: ToolCallSummary,
        tool_responses: list[ToolResponse],
        using_tool_calling_llm: bool,
    ) -> AnswerPromptBuilder:
        response = cast(CustomToolCallSummary, tool_responses[0].response)

        # Handle non-file responses using parent class behavior
        if response.response_type not in ["image", "csv"]:
            return super().build_next_prompt(
                prompt_builder,
                tool_call_summary,
                tool_responses,
                using_tool_calling_llm,
            )

        # Handle image and CSV file responses
        file_type = (
            ChatFileType.IMAGE
            if response.response_type == "image"
            else ChatFileType.CSV
        )

        # Load files from storage
        files = []
        file_store = get_default_file_store()

        for file_id in response.tool_result.file_ids:
            try:
                file_io = file_store.read_file(file_id, mode="b")
                files.append(
                    InMemoryChatFile(
                        file_id=file_id,
                        filename=file_id,
                        content=file_io.read(),
                        file_type=file_type,
                    )
                )
            except Exception:
                logger.exception(f"Failed to read file {file_id}")

            # Update prompt with file content
            prompt_builder.update_user_prompt(
                build_custom_image_generation_user_prompt(
                    query=prompt_builder.get_user_message_content(),
                    files=files,
                    file_type=file_type,
                )
            )

        return prompt_builder

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        response = cast(CustomToolCallSummary, args[0].response)
        if isinstance(response.tool_result, CustomToolUserFileSnapshot):
            return response.tool_result.model_dump()
        return response.tool_result


def build_custom_tools_from_openapi_schema_and_headers(
    tool_id: int,
    openapi_schema: dict[str, Any],
    custom_headers: list[HeaderItemDict] | None = None,
    dynamic_schema_info: DynamicSchemaInfo | None = None,
    user_oauth_token: str | None = None,
) -> list[CustomTool]:
    if dynamic_schema_info:
        # Process dynamic schema information
        schema_str = json.dumps(openapi_schema)
        placeholders = {
            CHAT_SESSION_ID_PLACEHOLDER: dynamic_schema_info.chat_session_id,
            MESSAGE_ID_PLACEHOLDER: dynamic_schema_info.message_id,
        }

        for placeholder, value in placeholders.items():
            if value:
                schema_str = schema_str.replace(placeholder, str(value))

        openapi_schema = json.loads(schema_str)

    url = openapi_to_url(openapi_schema)
    method_specs = openapi_to_method_specs(openapi_schema)

    return [
        CustomTool(
            id=tool_id,
            method_spec=method_spec,
            base_url=url,
            custom_headers=custom_headers,
            user_oauth_token=user_oauth_token,
        )
        for method_spec in method_specs
    ]


if __name__ == "__main__":
    import openai
    from openai.types.chat.chat_completion_message_function_tool_call import (
        ChatCompletionMessageFunctionToolCall,
    )

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

    tools = build_custom_tools_from_openapi_schema_and_headers(
        tool_id=0,  # dummy tool id
        openapi_schema=openapi_schema,
        dynamic_schema_info=None,
    )

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
        tool_call = choice.message.tool_calls[0]
        if isinstance(tool_call, ChatCompletionMessageFunctionToolCall):
            for tool_response in tools[0].run(
                **json.loads(tool_call.function.arguments)
            ):
                print(tool_response)
