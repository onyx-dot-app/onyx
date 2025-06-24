import json
from typing import Any, cast, Generator

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.llm.interfaces import LLM
from onyx.utils.special_types import JSON_ro
from onyx.llm.models import PreviousMessage
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool_prompts import TOOL_ARG_SYSTEM_PROMPT, TOOL_ARG_USER_PROMPT
from onyx.utils.logger import setup_logger
from onyx.tools.tool_implementations.knowledge_map import config
from onyx.tools.tool_implementations.knowledge_map.knowledge_map_bd import (
    get_id_from_knowledge_map_bd,
    get_answer_from_knowledge_map_answer_bd)

logger = setup_logger()

knowledge_map_tool_description = """An API for Knowledge Map"""
KNOWLEDGE_MAP_RESPONSE_SUMMARY_ID = "knowledge_map_response_summary"


class KnowledgeMapResponseSummary(BaseModel):
    tool_result: dict


class KnowledgeMapTool(Tool):
    NAME = "knowledge_map_tool"

    def __init__(self, db_session: Session, llm: LLM):
        self.db_session = db_session
        self.llm = llm

    def name(self) -> str:
        return self.NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name(),
                "description": knowledge_map_tool_description,
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
        response = cast(KnowledgeMapResponseSummary, args[0].response)
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
                        tool_name=self.name(),
                        tool_description=knowledge_map_tool_description,
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
            f"Failed to parse args for '{self.name()}' tool. Received: {args_result_str}"
        )
        return None

    def run(self, **kwargs: Any) -> Generator[ToolResponse, None, None]:
        item_list_knowledge_map = get_id_from_knowledge_map_bd(
            self.db_session
        )
        response = self.llm.invoke(
            [
                HumanMessage(
                    content=(
                        f"{config.MODEL_PROMT}\n\n"
                        f"{config.USER_QUERY_PROMT}: {kwargs['question']}\n\n"
                        f"{config.KNOWLEDGE_MAP_PROMT}: {item_list_knowledge_map}"
                    )
                )
            ]
        )
        knowledge_map_id = int(response.content.strip())
        if knowledge_map_id == 0:
            yield ToolResponse(
                id=KNOWLEDGE_MAP_RESPONSE_SUMMARY_ID,
                response=KnowledgeMapResponseSummary(
                    tool_result={
                        "text": knowledge_map_id
                    }
                ),
            )        
        item_list_knowledge_map_answer = get_answer_from_knowledge_map_answer_bd(
            self.db_session,
            knowledge_map_id
        )

        yield ToolResponse(
            id=KNOWLEDGE_MAP_RESPONSE_SUMMARY_ID,
            response=KnowledgeMapResponseSummary(
                tool_result={
                    "text": (
                        f"{config.USER_QUERY_PROMT}: {kwargs['question']}\n\n"
                        f"{config.KNOWLEDGE_MAP_PROMT}: {item_list_knowledge_map_answer}"
                    )
                }
            ),
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        return cast(KnowledgeMapResponseSummary, args[0].response).tool_result


def build_user_message_for_knowledge_map_tool(
        query: str,
        tool_name: str,
        *args: ToolResponse,
) -> str:
    tool_run_summary = cast(KnowledgeMapResponseSummary, args[0].response).tool_result
    return f"""
Here's the result from the {tool_name} tool:

{tool_run_summary}

Now respond to the following:

{query}
""".strip()
