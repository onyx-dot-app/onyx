import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.sub_agents.states import IterationAnswer
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.configs.constants import MessageType
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.utils import build_content_with_imgs
from onyx.prompts.dr_prompts import CUSTOM_TOOL_PREP_PROMPT
from onyx.prompts.dr_prompts import PYTHON_TOOL_USE_RESPONSE_PROMPT
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.python.python_tool import PythonToolResult
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _serialize_chat_files(chat_files: list[InMemoryChatFile]) -> list[dict[str, Any]]:
    serialized_files: list[dict[str, Any]] = []
    for chat_file in chat_files:
        file_payload: dict[str, Any] = {
            "id": str(chat_file.file_id),
            "name": chat_file.filename,
            "type": chat_file.file_type.value,
        }
        if chat_file.file_type == ChatFileType.IMAGE:
            file_payload["content"] = chat_file.to_base64()
            file_payload["is_base64"] = True
        elif chat_file.file_type.is_text_file():
            file_payload["content"] = chat_file.content.decode(
                "utf-8", errors="replace"
            )
            file_payload["is_base64"] = False
        else:
            file_payload["content"] = base64.b64encode(chat_file.content).decode(
                "utf-8"
            )
            file_payload["is_base64"] = True
        serialized_files.append(file_payload)

    return serialized_files


def python_tool_act(
    state: BranchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> BranchUpdate:
    """Execute the Python Tool with any files supplied by the user."""

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    tool_key = state.tools_used[-1]
    python_tool_info = state.available_tools[tool_key]
    python_tool = cast(PythonTool | None, python_tool_info.tool_object)

    if python_tool is None:
        raise ValueError("python_tool is not set")

    branch_query = state.branch_question
    if not branch_query:
        raise ValueError("branch_query is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query
    files = graph_config.inputs.files

    logger.debug(
        "Tool call start for %s %s.%s at %s",
        python_tool.llm_name,
        iteration_nr,
        parallelization_nr,
        datetime.now(),
    )

    tool_args: dict[str, Any] | None = None
    if graph_config.tooling.using_tool_calling_llm:
        tool_use_prompt = CUSTOM_TOOL_PREP_PROMPT.build(
            query=branch_query,
            base_question=base_question,
            tool_description=python_tool_info.description,
        )

        content_with_files = build_content_with_imgs(
            message=tool_use_prompt,
            files=files,
            message_type=MessageType.USER,
        )

        tool_prompt_message: dict[str, Any] = {
            "role": "user",
            "content": content_with_files,
        }
        if files:
            tool_prompt_message["files"] = _serialize_chat_files(files)

        tool_calling_msg = graph_config.tooling.primary_llm.invoke(
            [tool_prompt_message],
            tools=[python_tool.tool_definition()],
            tool_choice="required",
            timeout_override=TF_DR_TIMEOUT_SHORT,
        )

        if isinstance(tool_calling_msg, AIMessage) and tool_calling_msg.tool_calls:
            tool_args = tool_calling_msg.tool_calls[0].get("args")
        else:
            logger.warning("Tool-calling LLM did not emit a tool call for Python Tool")

    if tool_args is None:
        tool_args = python_tool.get_args_for_non_tool_calling_llm(
            query=branch_query,
            history=[],
            llm=graph_config.tooling.primary_llm,
            force_run=True,
        )

    if tool_args is None:
        raise ValueError("Failed to obtain tool arguments from LLM")

    if "files" in tool_args:
        tool_args = {key: value for key, value in tool_args.items() if key != "files"}

    override_kwargs = {"files": files or []}

    tool_responses = list(python_tool.run(override_kwargs=override_kwargs, **tool_args))

    python_tool_result: PythonToolResult | None = None
    for response in tool_responses:
        if isinstance(response.response, PythonToolResult):
            python_tool_result = response.response
            break

    if python_tool_result is None:
        raise ValueError("Python tool did not return a valid result")

    final_result = python_tool.final_result(*tool_responses)
    tool_result_str = json.dumps(final_result, ensure_ascii=False)

    tool_summary_prompt = PYTHON_TOOL_USE_RESPONSE_PROMPT.build(
        base_question=base_question,
        tool_response=tool_result_str,
    )

    initial_files = list(files or [])
    generated_files: list[InMemoryChatFile] = []
    for artifact in python_tool_result.artifacts:
        if not artifact.file_id:
            continue

        chat_file = python_tool._available_files.get(artifact.file_id)
        if not chat_file:
            logger.warning(
                "Generated artifact with id %s not found in available files",
                artifact.file_id,
            )
            continue

        filename = (
            chat_file.filename
            or artifact.display_name
            or artifact.path
            or str(artifact.file_id)
        )
        filename = Path(filename).name or str(artifact.file_id)
        if not filename.startswith("generated_"):
            filename = f"generated_{filename}"

        generated_files.append(
            InMemoryChatFile(
                file_id=chat_file.file_id,
                content=chat_file.content,
                file_type=chat_file.file_type,
                filename=filename,
            )
        )

    summary_files = initial_files + generated_files
    summary_content = build_content_with_imgs(
        message=tool_summary_prompt,
        files=summary_files,
        message_type=MessageType.USER,
    )

    summary_message: dict[str, Any] = {
        "role": "user",
        "content": summary_content,
    }
    if summary_files:
        summary_message["files"] = _serialize_chat_files(summary_files)

    answer_string = str(
        graph_config.tooling.primary_llm.invoke(
            [summary_message],
            timeout_override=TF_DR_TIMEOUT_SHORT,
        ).content
    ).strip()

    artifact_file_ids = [
        artifact.file_id
        for artifact in python_tool_result.artifacts
        if artifact.file_id
    ]

    logger.debug(
        "Tool call end for %s %s.%s at %s",
        python_tool.llm_name,
        iteration_nr,
        parallelization_nr,
        datetime.now(),
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=python_tool.llm_name,
                tool_id=python_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=branch_query,
                answer=answer_string,
                claims=[],
                cited_documents={},
                reasoning="",
                additional_data=None,
                response_type="json",
                data=final_result,
                file_ids=artifact_file_ids or None,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="python_tool",
                node_name="tool_calling",
                node_start_time=node_start_time,
            )
        ],
    )
