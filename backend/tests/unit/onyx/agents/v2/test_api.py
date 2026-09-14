from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from fastapi.routing import APIRoute

from onyx.agents.v2.models import (
    HarnessPolicy,
    HarnessResult,
    RegisteredTool,
    ToolOutput,
    UsageSnapshot,
)
from onyx.context.search.models import BaseFilters, PersonaSearchInfo
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLMConfig
from onyx.server.features.harness_v2 import api as module
from onyx.server.features.harness_v2.api import external_registration, require_enabled
from onyx.server.features.harness_v2.models import AgentRequest
from onyx.server.settings.models import Settings


def test_routes_have_separate_explicit_paths() -> None:
    from onyx.server.features.harness_v2.api import router

    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}
    assert paths == {
        "/harness/v2/run",
        "/harness/v2/capabilities",
        "/harness/v2/profile",
        "/harness/v2/playground",
        "/harness/v2/guide",
    }


def test_feature_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_AGENT_HARNESS_V2", raising=False)
    with pytest.raises(OnyxError) as exc:
        require_enabled()
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
    monkeypatch.setenv("ENABLE_AGENT_HARNESS_V2", "true")
    require_enabled()


def test_request_cannot_grant_tool_approval() -> None:
    with pytest.raises(ValueError):
        AgentRequest.model_validate(
            {"question": "hello", "approved_tools": ["external__write"]}
        )
    with pytest.raises(ValueError):
        AgentRequest(question="hello", include_persona_tools=True)
    with pytest.raises(ValueError):
        AgentRequest(question="hello", model="gpt-5-mini")


def test_external_registration_requires_server_approval() -> None:
    class FakeTool:
        name = "write"
        description = "Write data"

        def tool_definition(self) -> dict[str, Any]:
            return {"function": {"parameters": {"type": "object"}}}

    from onyx.tools.interface import Tool

    tool = cast(Tool, FakeTool())
    assert external_registration(tool, set()).requires_approval
    assert not external_registration(tool, {"external__write"}).requires_approval


@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        (False, False),
        (True, True),
        (None, True),
    ],
)
@pytest.mark.parametrize("decision_mode", ["standard", "minimal"])
@pytest.mark.parametrize(
    "model_capacity,requested_cap,effective_cap",
    [
        (32000, None, 28800),
        (400000, None, 360000),
        (400000, 16000, 16000),
        (400000, 1000000, 360000),
    ],
)
def test_run_agent_inherits_auto_detect_filter_setting(
    monkeypatch: pytest.MonkeyPatch,
    setting: bool | None,
    expected: bool,
    decision_mode: Literal["standard", "minimal"],
    model_capacity: int,
    requested_cap: int | None,
    effective_cap: int,
) -> None:
    captured: dict[str, Any] = {}
    decision_args: dict[str, Any] = {}
    llm = SimpleNamespace(
        config=LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0,
            max_input_tokens=model_capacity,
        )
    )

    class FakeSearch:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def registered(self) -> RegisteredTool:
            return RegisteredTool(
                name="internal_search",
                description="Search",
                parameters={"type": "object"},
                execute=lambda _args, _context: ToolOutput(content="{}"),
                requires_approval=False,
            )

    class FakeHarness:
        def __init__(self, **kwargs: Any) -> None:
            captured["policy"] = kwargs["policy"]

        def run(self, task: str) -> HarnessResult:
            return HarnessResult(
                run_id="r1",
                outcome="completed",
                answer=task,
                reason="done",
                model_calls=0,
                tool_calls=0,
                total_ms=0,
                usage=UsageSnapshot(),
                events=[],
                receipts=[],
            )

    class FakeTrace:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(trace_id="trace")

        def __exit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(
        module,
        "prepare_harness",
        lambda *_args: SimpleNamespace(
            llm=llm,
            index=object(),
            persona=PersonaSearchInfo(
                document_set_names=[],
                search_start_date=None,
                attached_document_ids=[],
                hierarchy_node_ids=[],
            ),
            search_tool_id=1,
            external_tools=[],
        ),
    )
    monkeypatch.setattr(module, "get_llm_token_counter", lambda _llm: lambda _text: 1)
    monkeypatch.setattr(module, "InternalSearchAnswer", FakeSearch)
    monkeypatch.setattr(module, "AgentHarness", FakeHarness)

    def decision_model(*args: Any, **kwargs: Any) -> object:
        decision_args.update(kwargs)
        decision_args["llm"] = args[0]
        return object()

    minimal_llm = SimpleNamespace(config=llm.config)
    monkeypatch.setattr(module, "OnyxDecisionModel", decision_model)
    monkeypatch.setattr(
        module, "create_minimal_completion_llm", lambda _llm: minimal_llm
    )
    monkeypatch.setattr(
        module, "load_settings", lambda: Settings(auto_detect_search_filters=setting)
    )
    monkeypatch.setattr(module, "trace", lambda *_args, **_kwargs: FakeTrace())
    filters = BaseFilters(document_set=["selected"])

    module.run_agent(
        AgentRequest(
            question="What changed?",
            filters=filters,
            decision_mode=decision_mode,
            policy=HarnessPolicy(max_context_tokens=requested_cap),
        ),
        user=cast(User, SimpleNamespace(id="user")),
    )

    assert captured["auto_detect_filters"] is expected
    assert captured["filters"] is filters
    assert captured["policy"].max_context_tokens == effective_cap
    assert captured["policy"].max_total_tokens == 120000
    assert captured["llm"] is not decision_args["llm"]
    assert captured["llm"]._ledger is decision_args["llm"]._ledger
    assert captured["reasoning_effort"].value == "low"
    assert captured["concise_answers"] is False
    assert captured["synthesize_answer"] is False
    assert decision_args["completion_llm"] is None
    if decision_mode == "minimal":
        assert decision_args["minimal_decision_llm"] is not captured["llm"]
        assert decision_args["minimal_decision_llm"]._inner is minimal_llm
        assert decision_args["minimal_decision_llm"]._ledger is captured["llm"]._ledger
    else:
        assert decision_args["minimal_decision_llm"] is None
