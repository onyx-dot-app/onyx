"""Project message content and detach SDK state for response persistence."""

from collections.abc import Mapping, Sequence
from functools import partial

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from onyx.agents.models import AgentInfo, RunState, StepRecord, ToolExecutionRecord
from onyx.chat.citation_processor import cited_documents
from onyx.chat.models import ChatMessageMetadata, MessageRendering, ResponseRecord
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchConfiguration
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.utils.logger import setup_logger
from onyx.utils.pydantic_util import as_base
from onyx.utils.streaming_json import parse_partial_object

_STRING = TypeAdapter(str)
logger = setup_logger()


def tool_arguments_for_display(call: ToolCall) -> dict[str, JsonValue]:
    """Decode interrupted arguments for display without making the call executable."""
    if call.arguments_complete or call.argument_error or not call.raw_arguments:
        return call.arguments
    try:
        return parse_partial_object(call.raw_arguments)
    except ValueError:
        logger.debug("Interrupted tool arguments cannot be displayed", exc_info=True)
        return call.arguments


def thinking_tool_text(call: ToolCall) -> str:
    try:
        return _STRING.validate_python(
            tool_arguments_for_display(call).get("reasoning", "")
        )
    except ValidationError:
        logger.debug("Thinking tool arguments are not text", exc_info=True)
        return ""


def message_thinking(
    message: AssistantMessage,
    think_tool: str | None = None,
    *,
    text_as_thinking: bool = False,
) -> str:
    """Collect model and configured-tool thinking in accepted content order."""
    return "".join(
        block.text
        if isinstance(block, (ThinkingContent, TextContent))
        else thinking_tool_text(block)
        for block in message.content
        if isinstance(block, ThinkingContent)
        or (text_as_thinking and isinstance(block, TextContent))
        or (isinstance(block, ToolCall) and block.name == think_tool)
    )


def response_record(
    snapshot: RunState, registrations: Sequence[AgentInfo] = ()
) -> ResponseRecord:
    """Detach accepted content before optional artifact and display processing.

    This aggregate retains concrete result objects in memory. Storage owns their
    typed encoding; the aggregate is not a standalone JSON persistence schema.
    """
    metadata = {info.id: info for info in registrations}

    def capture(node: RunState, *, is_root: bool = False) -> ResponseRecord:
        info = metadata.get(node.agent_id) if node.agent_id is not None else None
        if not is_root and info is None:
            raise ValueError("Child response requires its agent registration")
        configuration = info.restoration_config if info else None
        if configuration is not None and not isinstance(
            configuration, ResearchConfiguration
        ):
            raise ValueError("Unsupported saved child configuration")
        return ResponseRecord(
            run_id=node.run_id,
            agent_id=node.agent_id,
            agent_path=info.path if info else "/root",
            agent_description=info.description if info else "",
            restoration_config=configuration.model_copy(deep=True)
            if configuration
            else None,
            previous_run_id=node.previous_run_id,
            parent_run_id=node.parent_run_id,
            parent_tool_call_id=node.parent_tool_call_id,
            parent_message_id=node.parent_message_id,
            input_messages=[_saved_message(message) for message in node.input_messages],
            steps=[_saved_step(step) for step in node.steps],
            answer_step_index=node.answer_step_index,
            child_runs=[capture(child) for child in node.child_runs],
            status=node.status,
            failure=node.failure.model_copy(deep=True) if node.failure else None,
            checkpoint=node.checkpoint.model_copy(deep=True)
            if node.checkpoint
            else None,
        )

    return capture(snapshot, is_root=True)


def response_snapshot(record: ResponseRecord) -> RunState:
    """Restore detached execution state from accepted response content."""
    return RunState(
        run_id=record.run_id,
        agent_id=record.agent_id,
        previous_run_id=record.previous_run_id,
        parent_run_id=record.parent_run_id,
        parent_tool_call_id=record.parent_tool_call_id,
        parent_message_id=record.parent_message_id,
        input_messages=[
            message.model_copy(deep=True) for message in record.input_messages
        ],
        steps=[step.model_copy(deep=True) for step in record.steps],
        answer_step_index=record.answer_step_index,
        child_runs=[response_snapshot(child) for child in record.child_runs],
        status=record.status,
        failure=record.failure.model_copy(deep=True) if record.failure else None,
        checkpoint=record.checkpoint.model_copy(deep=True)
        if record.checkpoint
        else None,
    )


def _cited_documents(
    citation_mapping: Mapping[int, str], documents: Mapping[str, SearchDoc]
) -> list[SearchDoc]:
    """The known documents of the citation numbers, each once, in mapping order."""
    return list(
        {
            document.document_id: document
            for document in cited_documents(citation_mapping, documents).values()
        }.values()
    )


def _restored_call(
    call: CodeModeCall, documents: Mapping[str, SearchDoc]
) -> CodeModeCall:
    details = call.details
    if not isinstance(details, SearchDocsResponse):
        return call
    ids = call.displayed_document_ids
    return call.model_copy(
        update={
            "details": details.model_copy(
                update={
                    "search_docs": _cited_documents(
                        details.citation_mapping, documents
                    ),
                    "displayed_docs": None
                    if ids is None
                    else [documents[key] for key in ids if key in documents],
                }
            )
        }
    )


def restore_result_documents[T: BaseModel](
    details: T, documents: Mapping[str, SearchDoc]
) -> T:
    """Refill the documents that saved tool results keep only as citation numbers."""
    if isinstance(details, SearchDocsResponse):
        return details.model_copy(
            update={
                "search_docs": _cited_documents(details.citation_mapping, documents)
            }
        )
    if isinstance(details, CodeModeExecutionResult):
        return details.map_calls(partial(_restored_call, documents=documents))
    return details


def restore_response_sources(
    messages: list[Message],
    documents: Mapping[str, SearchDoc],
    presentation: Mapping[str, MessageRendering],
) -> None:
    """Attach sources to an owned history list without changing its borrowed messages."""
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            rendering = presentation.get(message.id) if message.id is not None else None
            if rendering is not None and rendering.citation_documents:
                messages[index] = message.model_copy(
                    update={
                        "metadata": ChatMessageMetadata(
                            sources={
                                number: documents[document_id]
                                for number, document_id in rendering.citation_documents.items()
                                if document_id in documents
                            }
                        )
                    }
                )
            continue
        if not isinstance(message, ToolResultMessage) or message.details is None:
            continue
        details = restore_result_documents(message.details, documents)
        if details is not message.details:
            messages[index] = message.model_copy(update={"details": details})


def _saved_search(
    details: SearchDocsResponse, displayed_docs: list[SearchDoc] | None
) -> SearchDocsResponse:
    # Documents use their existing relation; staged files stay in execution state.
    return as_base(details, SearchDocsResponse).model_copy(
        update={"search_docs": [], "displayed_docs": displayed_docs}
    )


def _saved_call(call: CodeModeCall) -> CodeModeCall:
    # Planning metadata applies to the current turn, as for direct calls.
    details = call.details
    if not isinstance(details, SearchDocsResponse):
        return call.model_copy(update={"metadata": None})
    displayed = details.displayed_docs
    return call.model_copy(
        update={
            "details": _saved_search(details, displayed_docs=None),
            "metadata": None,
            "displayed_document_ids": None
            if displayed is None
            else [doc.document_id for doc in displayed],
        }
    )


def _saved_details(details: BaseModel | None) -> BaseModel | None:
    if isinstance(details, SearchDocsResponse):
        return _saved_search(
            details, displayed_docs=[] if details.displayed_docs == [] else None
        )
    if isinstance(details, CodeModeExecutionResult):
        # Staged files stay in execution state; documents use the call relation.
        return as_base(details, CodeModeExecutionResult).map_calls(_saved_call)
    return details


def _saved_message[T: Message](message: T) -> T:
    update: dict[str, BaseModel | None] = {"metadata": None}
    if isinstance(message, ToolResultMessage):
        update["details"] = _saved_details(message.details)
    return message.model_copy(update=update).model_copy(deep=True)


def _saved_step(step: StepRecord) -> StepRecord:
    return StepRecord(
        message=_saved_message(step.message),
        generation_status=step.generation_status,
        tools={
            call_id: ToolExecutionRecord(
                status=execution.status,
                result=_saved_message(execution.result)
                if execution.result is not None
                else None,
            )
            for call_id, execution in step.tools.items()
        },
    )
