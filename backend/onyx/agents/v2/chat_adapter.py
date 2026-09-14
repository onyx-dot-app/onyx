"""Feature-flagged adapter into Onyx's existing chat stream and persistence."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from onyx.agents.v2.llm import (
    BudgetedLLM,
    BudgetLedger,
    OnyxDecisionModel,
    create_search_llm,
)
from onyx.agents.v2.models import HarnessPolicy
from onyx.agents.v2.runner import AgentHarness
from onyx.agents.v2.search import InternalSearchAnswer
from onyx.chat.citation_processor import CitationMode, DynamicCitationProcessor
from onyx.configs.constants import MessageType
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.models import ReasoningEffort
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    OverallStop,
    Packet,
    SearchToolStart,
    SectionEnd,
)
from onyx.tools.models import ToolCallInfo
from onyx.tools.tool_implementations.search.search_tool import SearchTool


def request_harness_enabled(request, session, n_models: int) -> bool:
    return (
        os.environ.get("ONYX_CHAT_HARNESS_V2", "false").lower() == "true"
        and n_models == 1
        and not request.deep_research
        and not session.project_id
        and not request.file_descriptors
        and session.incognito_record_mode is None
        and request.forced_tool_id is None
        and request.allowed_tool_ids != []
        and not request.additional_context
    )


def chat_harness_enabled(setup, n_models: int, tools=None) -> bool:
    """Start with ordinary single-model, text-only, non-project chat.

    Other modes retain their existing loop and recording/privacy behavior.
    """
    return (
        os.environ.get("ONYX_CHAT_HARNESS_V2", "false").lower() == "true"
        and n_models == 1
        and not setup.new_msg_req.deep_research
        and not setup.chat_session_project_id
        and not setup.new_msg_req.file_descriptors
        and not setup.extracted_context_files.file_metadata
        and not setup.search_params.project_id_filter
        and not setup.search_params.persona_id_filter
        and setup.incognito_record_mode is None
        and setup.forced_tool_id is None
        and not setup.new_msg_req.additional_context
        and tools is not None
        and any(isinstance(tool, SearchTool) for tool in tools)
    )


def run_chat_harness(*, setup, user, emitter, state, tools) -> None:  # noqa: C901
    search_tool = next((tool for tool in tools if isinstance(tool, SearchTool)), None)
    if search_tool is None:
        raise ValueError(
            "Harness v2 requires an assistant with internal search enabled"
        )
    if search_tool.bypass_acl:
        raise ValueError("Harness v2 chat requires document permission enforcement")
    profile = json.loads(
        Path(__file__)
        .parents[2]
        .joinpath("server/features/harness_v2/validated_profile.json")
        .read_text()
    )
    policy = HarnessPolicy.model_validate(profile["policy"])
    # Resolve through normal permission-checked provider configuration.
    from onyx.db.harness_v2 import prepare_harness

    prepared = prepare_harness(
        user, profile["provider"], profile["model"], setup.persona.id, False
    )
    inner = create_search_llm(prepared.llm, profile["model"])
    counter = get_llm_token_counter(inner)
    started = time.monotonic()

    def cancelled() -> bool:
        return not setup.check_is_connected()

    ledger = BudgetLedger(policy, counter, cancelled=cancelled, started_at=started)
    mapping = {}
    step = 0
    current_docs = []

    def packet_observer(packet):
        if not isinstance(packet.obj, SearchToolStart):
            emitter.emit(Packet(placement=Placement(turn_index=step), obj=packet.obj))

    def response_observer(response):
        nonlocal current_docs
        by_id = {doc.document_id: doc for doc in response.search_docs}
        for number, doc_id in response.citation_mapping.items():
            if doc_id in by_id:
                mapping[number] = by_id[doc_id]
        current_docs = list({doc.document_id: doc for doc in mapping.values()}.values())
        state.add_search_docs(current_docs)
        state.set_citation_mapping(mapping)

    search = InternalSearchAnswer(
        tool_id=search_tool.id,
        user=user,
        persona=search_tool.persona_search_info,
        filters=search_tool.user_selected_filters,
        index=search_tool.document_index,
        llm=BudgetedLLM(
            inner,
            ledger,
            max_output_tokens=policy.search_max_output_tokens,
            protected_tokens=policy.completion_reserve_tokens,
        ),
        reasoning_effort=ReasoningEffort.OFF,
        auto_detect_filters=False,
        feedback=policy.search_feedback,
        candidate_preparation=policy.search_candidate_preparation,
        hierarchical_selection=policy.search_hierarchical_selection,
        final_selection_limit=policy.search_final_selection_limit,
        task_anchor=policy.search_task_anchor,
        expansion_strategy="objective",
        packet_observer=packet_observer,
        response_observer=response_observer,
    )

    def execute(arguments, context):
        nonlocal step
        emitter.emit(
            Packet(placement=Placement(turn_index=step), obj=SearchToolStart())
        )
        try:
            output = search.run(arguments, context)
            state.add_tool_call(
                ToolCallInfo(
                    parent_tool_call_id=None,
                    turn_index=step,
                    tab_index=0,
                    tool_name=search_tool.name,
                    tool_call_id="harness_" + uuid.uuid4().hex,
                    tool_id=search_tool.id,
                    reasoning_tokens=None,
                    tool_call_arguments=arguments,
                    tool_call_response=output.content,
                    search_docs=current_docs,
                )
            )
            return output
        finally:
            emitter.emit(Packet(placement=Placement(turn_index=step), obj=SectionEnd()))
            step += 1

    messages = [
        m
        for m in setup.simple_chat_history
        if m.message_type in {MessageType.USER, MessageType.ASSISTANT}
    ]
    question = messages[-1].message if messages else setup.new_msg_req.message
    history = [
        {"role": m.message_type.value, "content": m.message} for m in messages[:-1]
    ][-12:]
    # Keep latest question authoritative; historical assistant prose is context,
    # not verified source evidence. No gold or benchmark identity enters chat.
    task = question
    if history:
        task = (
            "Conversation context (assistant statements are not verified evidence):\n"
            + json.dumps(history, ensure_ascii=False)[-24000:]
            + "\n\nCurrent user question:\n"
            + question
        )
    if setup.custom_agent_prompt:
        task = (
            "Assistant instructions:\n"
            + setup.custom_agent_prompt[:12000]
            + "\n\n"
            + task
        )
    channel_mode = (
        os.environ.get("ONYX_CHAT_HARNESS_V2_CHANNELS", "false").lower() == "true"
    )

    def on_commentary(message):
        nonlocal step
        if final_started or cancelled():
            return
        emitter.emit(
            Packet(placement=Placement(turn_index=step), obj=AgentResponseStart())
        )
        emitter.emit(
            Packet(
                placement=Placement(turn_index=step),
                obj=AgentResponseDelta(content=message.content),
            )
        )
        emitter.emit(Packet(placement=Placement(turn_index=step), obj=SectionEnd()))
        step += 1

    processor = DynamicCitationProcessor(
        citation_mode=CitationMode.HYPERLINK
        if setup.new_msg_req.include_citations
        else CitationMode.REMOVE
    )
    final_started = False
    raw_answer = ""
    text = ""

    def emit_final(token):
        nonlocal final_started, raw_answer, text
        if cancelled():
            return
        if not final_started:
            final_started = True
            elapsed = time.monotonic() - started
            state.set_pre_answer_processing_time(elapsed)
            processor.update_citation_mapping(mapping)
            emitter.emit(
                Packet(
                    placement=Placement(turn_index=step),
                    obj=AgentResponseStart(
                        final_documents=current_docs,
                        pre_answer_processing_seconds=elapsed,
                    ),
                )
            )
        if token is not None:
            raw_answer += token
        for item in processor.process_token(token):
            if isinstance(item, CitationInfo):
                state.add_emitted_citation(item.citation_number)
                emitter.emit(Packet(placement=Placement(turn_index=step), obj=item))
            else:
                text += item
                state.set_answer_tokens(text)
                emitter.emit(
                    Packet(
                        placement=Placement(turn_index=step),
                        obj=AgentResponseDelta(content=item),
                    )
                )
        state.set_citation_mapping(processor.citation_to_doc)

    streaming = (
        channel_mode
        and os.environ.get("ONYX_CHAT_HARNESS_V2_STREAMING", "false").lower() == "true"
    )
    native = None
    assistant_messages = []
    if channel_mode:
        from onyx.agents.v2.channel_model import ChannelDecisionModel, NativeChannelLLM

        native = NativeChannelLLM(
            inner, on_final_delta=emit_final if streaming else None, cancelled=cancelled
        )
        model = ChannelDecisionModel(BudgetedLLM(native, ledger), on_commentary)
        assistant_messages = model.messages
    else:
        model = OnyxDecisionModel(
            BudgetedLLM(inner, ledger),
            user_id=str(user.id),
            reasoning_effort=ReasoningEffort.OFF,
            operation_timeout_seconds=policy.model_timeout_seconds,
        )
    harness = AgentHarness(
        model=model,
        tools=[search.registered().model_copy(update={"execute": execute})],
        policy=policy,
        usage=ledger.snapshot,
        token_counter=counter,
        started_at=started,
        cancelled=cancelled,
    )
    from onyx.server.features.harness_v2.interactive_tracing import trace_run

    request = SimpleNamespace(
        question=task,
        model=profile["model"],
        reasoning_effort=ReasoningEffort.OFF,
        policy=policy,
    )
    with trace_run(request, str(user.id)) as traced:
        result = harness.run(task)
        if final_started:
            # Preserve an interrupted prefix; never append a replacement answer.
            if result.answer.startswith(raw_answer):
                emit_final(result.answer[len(raw_answer) :])
            elif result.outcome == "completed":
                result = result.model_copy(
                    update={
                        "outcome": "partial",
                        "reason": "Streamed answer did not match the terminal response",
                    }
                )
            result = result.model_copy(update={"answer": raw_answer})
        elif not cancelled():
            emit_final(
                result.answer or ("I could not complete this request. " + result.reason)
            )
        if final_started:
            emit_final(None)
        if traced is not None:
            traced.log(
                output=result.answer,
                metadata={
                    "outcome": result.outcome,
                    "chat_session_id": str(setup.chat_session_id),
                    "run_id": result.run_id,
                    "streaming": streaming,
                    "outer_stream_metrics": native.stream_metrics if native else [],
                },
            )
        trace_url = traced.link() if traced is not None else None
    state.set_request_params(
        {
            "harness": "v2",
            "profile": "repairs-full500-20260914",
            "model": "gpt-5.6-sol",
            "reasoning": {"effort": "none"},
            "outcome": result.outcome,
            "usage": result.usage.model_dump(),
            "braintrust_url": trace_url,
            "output_channels": channel_mode,
            "streaming": streaming,
            "outer_stream_metrics": native.stream_metrics if native else [],
            "assistant_messages": assistant_messages,
        }
    )
    if cancelled():
        return
    emitter.emit(Packet(placement=Placement(turn_index=step), obj=SectionEnd()))
    emitter.emit(Packet(placement=Placement(turn_index=step), obj=OverallStop()))
