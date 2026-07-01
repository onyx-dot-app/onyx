"""Unit tests for LoadSkillTool.

No live LLM, DB, or file store: a known skill body is patched in via
``render_skill_body`` and the emitter is a MagicMock that appends emitted
packets to a list, so we can assert the exact packets the FE relies on.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.tool_implementations.load_skill.load_skill_tool import LoadSkillTool

_KNOWN_BODY = "# TDD Helper\n\nALWAYS write a failing test first. MARKER_BODY_77\n"


def _make_skill(slug: str) -> SimpleNamespace:
    # Stand-in for the detached Skill ORM row; only column attrs are read.
    return SimpleNamespace(slug=slug, name=f"Skill {slug}", description=f"desc {slug}")


def _make_tool(available: list[SimpleNamespace]) -> tuple[LoadSkillTool, list]:
    emitted: list = []
    emitter = MagicMock()
    emitter.emit.side_effect = emitted.append
    tool = LoadSkillTool(
        tool_id=42,
        emitter=emitter,
        available_skills=available,  # type: ignore[arg-type]
        user=MagicMock(),
    )
    return tool, emitted


def test_load_skill_returns_body_for_available_slug() -> None:
    skill = _make_skill("tdd-helper")
    tool, emitted = _make_tool([skill])
    placement = Placement(turn_index=0)

    with (
        patch(
            "onyx.tools.tool_implementations.load_skill.load_skill_tool.render_skill_body",
            return_value=_KNOWN_BODY,
        ) as mock_render,
        patch(
            "onyx.tools.tool_implementations.load_skill.load_skill_tool."
            "get_session_with_current_tenant"
        ),
    ):
        tool.emit_start(placement)
        response = tool.run(placement, skill_slug="tdd-helper")

    mock_render.assert_called_once()
    # The full body is returned to the LLM and carried in the rich response.
    assert response.llm_facing_response == _KNOWN_BODY
    assert "MARKER_BODY_77" in response.llm_facing_response
    assert isinstance(response.rich_response, CustomToolCallSummary)
    assert response.rich_response.tool_result == _KNOWN_BODY

    # FE renders the call: a start packet then a delta carrying the result.
    start, delta = emitted[0].obj, emitted[1].obj
    assert isinstance(start, CustomToolStart)
    assert start.tool_name == "load_skill"
    assert isinstance(delta, CustomToolDelta)
    assert delta.tool_id == 42
    assert delta.data == _KNOWN_BODY


def test_load_skill_unavailable_slug_does_not_crash() -> None:
    tool, emitted = _make_tool([_make_skill("tdd-helper")])
    placement = Placement(turn_index=0)

    # render_skill_body must NOT be reached for an unknown slug.
    with patch(
        "onyx.tools.tool_implementations.load_skill.load_skill_tool.render_skill_body",
    ) as mock_render:
        response = tool.run(placement, skill_slug="does-not-exist")

    mock_render.assert_not_called()
    assert "not available" in response.llm_facing_response
    assert "does-not-exist" in response.llm_facing_response
    # A delta is still emitted so the call renders, with no crash.
    assert isinstance(emitted[0].obj, CustomToolDelta)


def test_tool_definition_requires_skill_slug() -> None:
    tool, _ = _make_tool([_make_skill("tdd-helper")])
    definition = tool.tool_definition()
    fn = definition["function"]
    assert fn["name"] == "load_skill"
    assert fn["parameters"]["required"] == ["skill_slug"]
    # Available slugs are surfaced in the param description to steer the model.
    assert "tdd-helper" in fn["parameters"]["properties"]["skill_slug"]["description"]
