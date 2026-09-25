"""Load saved response content into the public item stream."""

from collections.abc import Mapping

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.orm import Session

from onyx.agents.transcript import RunStatus
from onyx.chat.citation_utils import extract_citation_order_from_text
from onyx.chat.models import (
    ChatExecutionRecord,
    MessageRendering,
    PresentationMode,
    ResponseRecord,
)
from onyx.chat.renderer import MessageRenderer
from onyx.chat.response_items import (
    ResponseGeneration,
    ResponseToolCall,
    ResponseToolResult,
    group_response_items_by_step,
)
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    get_db_search_doc_by_id,
    translate_db_search_doc_to_saved_search_doc,
)
from onyx.db.chat_response import read_chat_execution
from onyx.db.models import ChatMessage, Tool, ToolCall
from onyx.db.tools import (
    get_response_tool_records,
    get_tools_by_ids,
    restore_tool_result,
)
from onyx.llm.models import ToolResultMessage
from onyx.server.query_and_chat.streaming_models import (
    CitationInfo,
    ItemUpdate,
    OverallStop,
    Packet,
    PacketIdentity,
    ReasoningItem,
    RunUpdate,
    TextItem,
    ToolItem,
    ToolMetadata,
    ToolStatus,
)
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_TOOL_METADATA = TypeAdapter(ToolMetadata)


def _saved_tool_item(record: ToolCall, tool: Tool) -> ToolItem:
    arguments = _JSON_OBJECT.validate_python(record.tool_call_arguments or {})
    result = restore_tool_result(
        ToolResultMessage(
            tool_call_id=str(record.id),
            tool_name=tool.name,
            content=record.tool_call_response or "",
        ),
        record,
        tool,
    )
    return ToolItem(
        name=tool.name,
        tool_id=record.tool_id,
        arguments={
            key: value for key, value in arguments.items() if key != "requestBody"
        },
        output=result.text if result.details is None else "",
        metadata=_TOOL_METADATA.validate_python(result.details.model_dump())
        if result.details is not None
        else None,
        status=ToolStatus.COMPLETE,
    )


def translate_assistant_message_to_packets(
    chat_message: ChatMessage, db_session: Session
) -> list[Packet]:
    execution = read_chat_execution(chat_message)
    if execution is not None:
        return _execution_packets(chat_message, execution, db_session)
    if chat_message.message_type != MessageType.ASSISTANT:
        raise ValueError(f"Chat message {chat_message.id} is not an assistant message")
    base = PacketIdentity(
        response_id=chat_message.id,
        run_id=str(chat_message.id),
        message_id=str(chat_message.id),
    )
    packets: list[Packet] = []
    tools = {
        tool.id: tool
        for tool in get_tools_by_ids(
            list(
                {
                    record.tool_id
                    for record in chat_message.tool_calls or []
                    if record.tool_id is not None
                }
            ),
            db_session,
        )
    }
    seen_reasoning: set[int] = set()
    for record in sorted(
        chat_message.tool_calls or [],
        key=lambda record: (record.turn_number, record.tab_index),
    ):
        identity = base.model_copy(
            update={
                "message_id": f"{chat_message.id}:{record.turn_number}",
                "part_id": "tool",
                "tool_call_id": str(record.id),
            }
        )
        if record.reasoning_tokens and record.turn_number not in seen_reasoning:
            packets.append(
                Packet(
                    identity=identity.model_copy(
                        update={"tool_call_id": None, "part_id": "reasoning"}
                    ),
                    obj=ItemUpdate(
                        item=ReasoningItem(
                            text=record.reasoning_tokens, status=RunStatus.COMPLETE
                        )
                    ),
                )
            )
            seen_reasoning.add(record.turn_number)
        tool = tools.get(record.tool_id)
        if tool is None:
            logger.debug("Saved tool %s is no longer available", record.tool_id)
            continue
        packets.append(
            Packet(
                identity=identity, obj=ItemUpdate(item=_saved_tool_item(record, tool))
            )
        )
    identity = base.model_copy(update={"message_id": f"{chat_message.id}:answer"})
    if chat_message.reasoning_tokens:
        packets.append(
            Packet(
                identity=identity.model_copy(update={"part_id": "reasoning"}),
                obj=ItemUpdate(
                    item=ReasoningItem(
                        text=chat_message.reasoning_tokens, status=RunStatus.COMPLETE
                    )
                ),
            )
        )
    citations: list[CitationInfo] = []
    for number, doc_id in (chat_message.citations or {}).items():
        if doc := get_db_search_doc_by_id(doc_id, db_session):
            citations.append(
                CitationInfo(citation_number=number, document_id=doc.document_id)
            )
    order = {
        number: index
        for index, number in enumerate(
            extract_citation_order_from_text(chat_message.message or "")
        )
    }
    citations.sort(key=lambda citation: order.get(citation.citation_number, len(order)))
    if chat_message.message:
        packets.append(
            Packet(
                identity=identity,
                obj=ItemUpdate(
                    item=TextItem(
                        text=chat_message.message,
                        status=RunStatus.COMPLETE,
                        documents=[
                            translate_db_search_doc_to_saved_search_doc(doc)
                            for doc in chat_message.search_docs
                        ],
                        citations=citations,
                    )
                ),
            )
        )
    packets.append(
        Packet(
            identity=base.model_copy(update={"part_id": "run"}),
            obj=OverallStop(
                stop_reason="user_cancelled"
                if "generation was stopped" in (chat_message.message or "").lower()
                else "finished"
            ),
        )
    )
    return packets


def _execution_packets(
    chat_message: ChatMessage, execution: ChatExecutionRecord, db_session: Session
) -> list[Packet]:
    records = {
        record.id: record
        for record in get_response_tool_records(
            [reference.record_id for reference in execution.tool_records],
            chat_message.chat_session_id,
            db_session,
        )
    }
    tools = {
        tool.id: tool
        for tool in get_tools_by_ids(
            list(
                {
                    record.tool_id
                    for record in records.values()
                    if record.tool_id is not None
                }
            ),
            db_session,
        )
    }
    references = {
        (reference.message_id, reference.tool_call_id): records[reference.record_id]
        for reference in execution.tool_records
    }
    documents = {
        doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
        for doc in chat_message.search_docs
    }
    for record in records.values():
        documents.update(
            {
                doc.document_id: translate_db_search_doc_to_saved_search_doc(doc)
                for doc in record.search_docs
            }
        )
    return _response_packets(
        execution.response,
        chat_message.id,
        references,
        tools,
        execution.presentation,
        documents,
    )


def _response_packets(
    response: ResponseRecord,
    response_id: int,
    records: dict[tuple[str, str], ToolCall],
    tools: dict[int, Tool],
    settings: dict[str, MessageRendering],
    documents: Mapping[str, SearchDoc],
    default_mode: PresentationMode = PresentationMode.ANSWER,
) -> list[Packet]:
    base = PacketIdentity(
        response_id=response_id,
        run_id=response.run_id,
        agent_id=response.agent_id,
        agent_path=response.agent_path,
        message_id=f"{response.run_id}:0",
        parent_run_id=response.parent_run_id,
        parent_message_id=response.parent_message_id,
        parent_tool_call_id=response.parent_tool_call_id,
    )
    packets: list[Packet] = []
    for items in group_response_items_by_step(response.items).values():
        generation = items[0]
        if not isinstance(generation.content, ResponseGeneration):
            raise ValueError("Response step has no generation boundary")
        identity = base.model_copy(update={"message_id": generation.id})
        renderer = MessageRenderer(
            settings.get(generation.id, MessageRendering(mode=default_mode)),
            documents,
            identity,
        )
        packets.extend(renderer.saved(items))
        results = {
            item.content.result.tool_call_id: item.content.result
            for item in items
            if isinstance(item.content, ResponseToolResult)
        }
        for item in items:
            if not isinstance(item.content, ResponseToolCall):
                continue
            call = item.content.call
            call_identity = identity.model_copy(
                update={"tool_call_id": call.id, "part_id": "tool"}
            )
            record = records.get((identity.message_id, call.id))
            tool = tools.get(record.tool_id) if record is not None else None
            result = results.get(call.id)
            if result is not None and record is not None:
                result = restore_tool_result(result, record, tool)
            packets.append(
                Packet(
                    identity=call_identity,
                    obj=ItemUpdate(
                        item=ToolItem(
                            name=call.name,
                            tool_id=record.tool_id if record is not None else None,
                            arguments={
                                key: value
                                for key, value in call.arguments.items()
                                if key != "requestBody"
                            },
                            output=result.text
                            if result is not None and result.details is None
                            else "",
                            metadata=_TOOL_METADATA.validate_python(
                                result.details.model_dump()
                            )
                            if result is not None and result.details is not None
                            else None,
                            status=ToolStatus(
                                (item.content.status or response.status).value
                            ),
                        )
                    ),
                )
            )
            for child in response.child_runs:
                if (
                    child.parent_message_id == identity.message_id
                    and child.parent_tool_call_id == call.id
                ):
                    child_mode = (
                        PresentationMode.CODING_THINKING
                        if tool is not None
                        and tool.in_code_tool_id == CodingAgentTool.__name__
                        else PresentationMode.ANSWER
                    )
                    packets.extend(
                        _response_packets(
                            child,
                            response_id,
                            records,
                            tools,
                            settings,
                            documents,
                            child_mode,
                        )
                    )
    packets.append(
        Packet(
            identity=base.model_copy(update={"part_id": "run"}),
            obj=RunUpdate(status=response.status),
        )
    )
    if response.parent_run_id is None and response.status.is_terminal:
        packets.append(
            Packet(
                identity=base.model_copy(update={"part_id": "run"}),
                obj=OverallStop(
                    stop_reason="user_cancelled"
                    if response.status == RunStatus.CANCELLED
                    else "finished"
                ),
            )
        )
    return packets
