"""The bundled ``linear_api.py`` sandbox helper: the pure ``IssueCreateInput``
builder used by ``create-issue``. The helper is a standalone script under the
skills dir (not an importable package), so load it by path. These tests require
no network and no onyx imports."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

_HELPER = (
    Path(__file__).resolve().parents[3] / "onyx/skills/builtin" / "linear/linear_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("linear_api", _HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


linear = _load()


def _args(**overrides: object) -> argparse.Namespace:
    """A create-issue namespace with every optional flag unset by default."""
    base: dict[str, object] = {
        "team_id": "TEAM1",
        "title": "Fix the bug",
        "description": None,
        "assignee": None,
        "project": None,
        "state": None,
        "priority": None,
        "label": None,
        "estimate": None,
        "parent": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_build_input_minimal_only_team_and_title() -> None:
    inp = linear._build_issue_create_input(_args())
    assert inp == {"teamId": "TEAM1", "title": "Fix the bug"}


def test_build_input_maps_all_provided_flags() -> None:
    inp = linear._build_issue_create_input(
        _args(
            description="Steps to repro",
            assignee="USER1",
            project="PROJ1",
            state="STATE1",
            priority=2,
            label=["LBL1", "LBL2"],
            estimate=5,
            parent="ISSUE1",
        )
    )
    assert inp == {
        "teamId": "TEAM1",
        "title": "Fix the bug",
        "description": "Steps to repro",
        "assigneeId": "USER1",
        "projectId": "PROJ1",
        "stateId": "STATE1",
        "priority": 2,
        "labelIds": ["LBL1", "LBL2"],
        "estimate": 5,
        "parentId": "ISSUE1",
    }


def test_build_input_omits_unset_keys() -> None:
    inp = linear._build_issue_create_input(_args(project="PROJ1"))
    assert inp == {"teamId": "TEAM1", "title": "Fix the bug", "projectId": "PROJ1"}
    for absent in (
        "description",
        "assigneeId",
        "stateId",
        "priority",
        "labelIds",
        "estimate",
        "parentId",
    ):
        assert absent not in inp


def test_build_input_priority_zero_is_kept() -> None:
    # 0 (no priority) and estimate 0 carry signal and must not be dropped.
    inp = linear._build_issue_create_input(_args(priority=0, estimate=0))
    assert inp["priority"] == 0
    assert inp["estimate"] == 0


def test_build_input_single_repeatable_label() -> None:
    inp = linear._build_issue_create_input(_args(label=["LBL1"]))
    assert inp["labelIds"] == ["LBL1"]


def test_build_input_state_id_passed_through() -> None:
    # The pure builder treats a.state as an already-resolved id (resolution of a
    # state *name* happens in the dispatch path, not here).
    inp = linear._build_issue_create_input(_args(state="resolved-state-id"))
    assert inp["stateId"] == "resolved-state-id"


def test_resolve_state_id_returns_uuid_without_network() -> None:
    # A UUID is returned as-is, so no GraphQL call is made.
    uuid = "12345678-1234-1234-1234-1234567890ab"
    assert linear._resolve_state_id("TEAM1", uuid) == uuid


def test_resolve_state_id_matches_name_case_insensitively(monkeypatch) -> None:
    monkeypatch.setattr(
        linear,
        "_gql",
        lambda _q, _v: {
            "data": {
                "team": {
                    "states": {
                        "nodes": [
                            {"id": "s-todo", "name": "Todo"},
                            {"id": "s-prog", "name": "In Progress"},
                        ]
                    }
                }
            }
        },
    )
    assert linear._resolve_state_id("TEAM1", "in progress") == "s-prog"


def test_resolve_state_id_raises_on_unknown_name(monkeypatch) -> None:
    monkeypatch.setattr(
        linear,
        "_gql",
        lambda _q, _v: {"data": {"team": {"states": {"nodes": []}}}},
    )
    try:
        linear._resolve_state_id("TEAM1", "Nonexistent")
    except ValueError as e:
        assert "Nonexistent" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown state name")


def test_create_issue_parser_has_new_flags() -> None:
    args = linear._build_parser().parse_args(
        [
            "create-issue",
            "TEAM1",
            "Title",
            "--project",
            "PROJ1",
            "--state",
            "Todo",
            "--priority",
            "1",
            "--label",
            "LBL1",
            "--label",
            "LBL2",
            "--estimate",
            "3",
            "--parent",
            "ISSUE1",
        ]
    )
    assert args.project == "PROJ1"
    assert args.state == "Todo"
    assert args.priority == 1
    assert args.label == ["LBL1", "LBL2"]
    assert args.estimate == 3
    assert args.parent == "ISSUE1"
