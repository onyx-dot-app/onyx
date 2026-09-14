from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from onyx.agents.v2.llm import (
    BudgetedLLM,
    BudgetLedger,
    OnyxDecisionModel,
    create_minimal_completion_llm,
    create_search_llm,
)
from onyx.agents.v2.models import ExecutionContext, RegisteredTool, ToolOutput
from onyx.agents.v2.runner import AgentHarness
from onyx.agents.v2.search import InternalSearchAnswer
from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.harness_v2 import prepare_harness
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_llm_token_counter
from onyx.server.features.harness_v2.models import AgentRequest, AgentResponse
from onyx.server.query_and_chat.placement import Placement
from onyx.server.settings.store import load_settings
from onyx.server.utils_vector_db import require_vector_db
from onyx.tools.interface import Tool
from onyx.tracing.framework.create import trace


def require_enabled() -> None:
    if os.environ.get("ENABLE_AGENT_HARNESS_V2", "false").lower() != "true":
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Experimental harness is disabled")


router = APIRouter(
    prefix="/harness/v2",
    dependencies=[Depends(require_enabled), Depends(require_vector_db)],
)


def external_registration(tool: Tool, approved_names: set[str]) -> RegisteredTool:
    definition = tool.tool_definition()["function"]
    name = "external__" + tool.name

    def execute(arguments: dict[str, Any], context: ExecutionContext) -> ToolOutput:
        if context.cancelled():
            return ToolOutput(status="blocked", content="Task was cancelled")
        response = tool.run(
            placement=Placement(turn_index=0), override_kwargs=None, **arguments
        )
        return ToolOutput(
            content=response.llm_facing_response, receipt={"external_tool": tool.name}
        )

    return RegisteredTool(
        name=name,
        description=tool.description,
        parameters=definition["parameters"],
        execute=execute,
        requires_approval=name not in approved_names,
    )


@router.post("/run", dependencies=[Depends(require_permission(Permission.WRITE_CHAT))])
def run_agent(
    request: AgentRequest,
    user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> AgentResponse:
    started = time.monotonic()
    prepared = prepare_harness(
        user,
        request.provider,
        request.model,
        request.persona_id,
        request.include_persona_tools,
    )
    if (
        request.model in {"gpt-5.6-luna", "gpt-5.6-sol"}
        and request.reasoning_effort.value == "off"
    ):
        prepared.llm = create_search_llm(prepared.llm, request.model)
    counter = get_llm_token_counter(prepared.llm)
    model_context_limit = int(prepared.llm.config.max_input_tokens * 0.9)
    policy = request.policy.model_copy(
        update={
            "max_context_tokens": min(
                request.policy.max_context_tokens or model_context_limit,
                model_context_limit,
            )
        }
    )
    shared_started_at = time.monotonic() if policy.duration_mode == "soft" else None
    ledger = BudgetLedger(
        policy=policy, token_counter=counter, started_at=shared_started_at
    )
    llm = BudgetedLLM(prepared.llm, ledger)
    completion_llm = None
    minimal_decision_llm = None
    if request.completion_mode == "minimal" or request.decision_mode == "minimal":
        try:
            minimal_llm = BudgetedLLM(
                create_minimal_completion_llm(prepared.llm), ledger
            )
            if request.completion_mode == "minimal":
                completion_llm = minimal_llm
            if request.decision_mode == "minimal":
                minimal_decision_llm = minimal_llm
        except ValueError as exc:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc
    search = InternalSearchAnswer(
        tool_id=prepared.search_tool_id,
        user=user,
        persona=prepared.persona,
        filters=request.filters,
        index=prepared.index,
        llm=BudgetedLLM(
            create_search_llm(prepared.llm, policy.search_model),
            ledger,
            max_output_tokens=policy.search_max_output_tokens,
            protected_tokens=policy.completion_reserve_tokens
            if policy.protect_search_budget
            else 0,
        ),
        reasoning_effort=request.reasoning_effort,
        auto_detect_filters=load_settings().auto_detect_search_filters is not False,
        concise_answers=request.concise_answers,
        synthesize_answer=request.search_synthesis,
        feedback=policy.search_feedback,
        candidate_preparation=policy.search_candidate_preparation,
        hierarchical_selection=policy.search_hierarchical_selection,
        final_selection_limit=policy.search_final_selection_limit,
        document_read=policy.search_document_read,
        task_anchor=policy.search_task_anchor,
        expansion_strategy=request.search_expansion_strategy,
    )
    approved = {
        name.strip()
        for name in os.environ.get("ONYX_V2_APPROVED_TOOLS", "").split(",")
        if name.strip()
    }
    sources: dict[int, dict] = {}

    def search_with_sources(
        arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolOutput:
        output = search.run(arguments, context)
        try:
            evidence = json.loads(output.content)
            for document in evidence.get("results", []):
                number = document.get("document")
                if isinstance(number, int):
                    sources[number] = {
                        "citation": number,
                        "title": document.get("title", ""),
                        "content": document.get("content", ""),
                        "document_id": output.citation_mapping.get(number),
                    }
        except (ValueError, AttributeError, TypeError):
            pass
        return output

    tools = [
        search.registered().model_copy(update={"execute": search_with_sources}),
        *(external_registration(tool, approved) for tool in prepared.external_tools),
    ]
    model = OnyxDecisionModel(
        llm,
        source_cards=policy.source_cards,
        user_id=str(user.id),
        reasoning_effort=request.reasoning_effort,
        completion_llm=completion_llm,
        minimal_decision_llm=minimal_decision_llm,
        operation_timeout_seconds=policy.model_timeout_seconds
        if policy.duration_mode == "soft"
        else None,
    )
    harness = AgentHarness(
        model=model,
        tools=tools,
        policy=policy,
        usage=ledger.snapshot,
        token_counter=counter,
        started_at=shared_started_at,
    )
    setup_ms = (time.monotonic() - started) * 1000
    from onyx.server.features.harness_v2.interactive_tracing import trace_run

    with trace_run(request, str(user.id)) as traced:
        with trace(
            "search_first_harness_v2",
            metadata={"user_id": str(user.id), "variant": "v2"},
        ) as span:
            result = harness.run(request.question)
            trace_id = span.trace_id
        if traced is not None:
            traced.log(
                output=result.answer,
                metadata={"outcome": result.outcome, "run_id": result.run_id},
            )
        trace_url = traced.link() if traced is not None else None
    return AgentResponse(
        result=result,
        setup_ms=round(setup_ms, 3),
        request_total_ms=round((time.monotonic() - started) * 1000, 3),
        trace_id=trace_id,
        trace_url=trace_url,
        sources=list(sources.values()),
    )


@router.get("/capabilities")
def capabilities(
    _user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> dict[str, Any]:
    return {
        "variant": "search_first_v2",
        "default_changed": False,
        "selective_tool_discovery": True,
        "result_store_scope": "current_request",
        "search_owns_synthesis": False,
        "search_synthesis_opt_in": True,
        "external_tools_require_persona_and_server_approval": True,
        "deadline_enforcement": "cooperative; adapters must honor deadlines",
        "outcomes": [
            "completed",
            "partial",
            "needs_user_input",
            "blocked",
            "budget_exhausted",
            "cancelled",
        ],
        "policy_schema": AgentRequest.model_json_schema(),
    }


@router.get("/profile")
def validated_profile(
    _user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("validated_profile.json").read_text())


@router.get("/playground", response_class=HTMLResponse)
def playground(
    _user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> HTMLResponse:
    return HTMLResponse(
        Path(__file__).with_name("playground.html").read_text(),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/guide", response_class=HTMLResponse)
def guide(
    _user: User = Depends(require_permission(Permission.READ_SEARCH)),
) -> HTMLResponse:
    return HTMLResponse(
        Path(__file__).with_name("guide.html").read_text(),
        headers={"Cache-Control": "no-store"},
    )
