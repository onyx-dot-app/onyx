import json
import os
from typing import Any, cast, Generator

import requests
from docxtpl import DocxTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder, default_build_system_message
from onyx.configs.app_configs import FLOWISE_BASE_URL, FLOWISE_API_KEY
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.message import ToolCallSummary
from onyx.utils.special_types import JSON_ro
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool_prompts import TOOL_ARG_SYSTEM_PROMPT, TOOL_ARG_USER_PROMPT
from onyx.tools.tool_implementations.resume.minio_requests import (
    minio_get_object_template,
    minio_get_bytes,
    minio_put_object,
    minio_get_object_url)
from onyx.utils.logger import setup_logger

TEXT_SECTION_SEPARATOR = "\n\n"
logger = setup_logger()

resume_tool_description = """An API for Resume"""
RESUME_RESPONSE_SUMMARY_ID = "resume_response_summary"

DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


class ResumeResponseSummary(BaseModel):
    tool_result: dict
    tool_name: str


class ResumeTool(Tool):
    NAME = "resume_tool"
    _DISPLAY_NAME = "Doc Formatter"

    def __init__(self, db_session: Session, pipeline_id: str, docs: list, template_file: str, prompt_config, llm_config):  # , template_name: str
        self.db_session = db_session
        self.pipeline_id = pipeline_id
        self.base_url = FLOWISE_BASE_URL
        self.docs = docs
        self.template_file = template_file
        self.prompt_config = prompt_config
        self.llm_config = llm_config
        # self.template_name = template_name

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return ""

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": resume_tool_description,
                "parameters": {
                    "type": "document",
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
        response = cast(ResumeResponseSummary, args[0].response)
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
                        tool_description=resume_tool_description,
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

    def download_word(self, data, template_file_name) -> str:
        minio_get_object_template(template_file_name)
        tpl = DocxTemplate(os.path.join(DOWNLOAD_FOLDER, template_file_name))

        value = data.get('name', None)
        file_name = f"{value.replace(' ', '_')}_Резюме.docx" if value else 'Резюме.docx'

        tpl.render(data)
        tpl.save(os.path.join(DOWNLOAD_FOLDER, file_name))
        os.remove(os.path.join(DOWNLOAD_FOLDER, template_file_name))
        return file_name

    def run(self, **kwargs: Any) -> Generator[ToolResponse, None, None]:
        document_name = self.docs[0]['name']
        logger.info(document_name)
        document_bytes = minio_get_bytes(document_name)
        url = self.base_url + f"/api/v1/prediction/{self.pipeline_id}"
        request_body = {"question": document_bytes}
        headers = {"Authorization": "Bearer " + FLOWISE_API_KEY}
        response = requests.post(url, data=request_body, headers=headers)
        response_json = json.loads(response.text)
        text_response = response_json['text']

        if '```json' in text_response:
            json_text = text_response.split('```json', 1)[1].strip().rstrip('```')
        else:
            json_text = text_response.strip()

        data = json.loads(json_text)

        output_file_name = self.download_word(data, self.template_file)
        output_file_path = os.path.join(DOWNLOAD_FOLDER, output_file_name)
        minio_put_object(output_file_path)

        output_file_url = minio_get_object_url(output_file_path)

        yield ToolResponse(
            id=RESUME_RESPONSE_SUMMARY_ID,
            response=ResumeResponseSummary(tool_result={"text": output_file_url}, tool_name=self.name),
        )
        os.remove(os.path.join(DOWNLOAD_FOLDER, output_file_name))

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return cast(ResumeResponseSummary, args[0].response).tool_result

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

        tool_summary = tool_responses[0].response if tool_responses else None
        tool_result = cast(ResumeResponseSummary, tool_summary).tool_result if tool_summary else {}
        query = prompt_builder.get_user_message_content()

        logger.info(tool_result)
        logger.info(query)
        logger.info(tool_responses)

        prompt_builder.update_user_prompt(
            HumanMessage(
                content=build_user_message_for_resume_tool(
                    query=query,
                    tool_name=self.name,
                    tool_result=tool_result,
                )
            )
        )

        return prompt_builder


def build_user_message_for_resume_tool(
        query: str,
        tool_name: str,
    tool_result: dict,
) -> str:
    return f"""
Here's the result from the {tool_name} tool:

{tool_result}

Now respond to the following:

{query}
""".strip()
