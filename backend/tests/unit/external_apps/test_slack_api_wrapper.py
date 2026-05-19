"""Unit tests for the bundled Slack wrapper's pure logic (_prune,
_paginate). The wrapper is a sandbox script, not a package module, so
it's loaded by path. HTTP is mocked — these never touch the network."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_WRAPPER = (
    Path(__file__).parents[3] / "onyx/external_apps/skill_bundles/slack/slack_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slack_api", _WRAPPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


slack_api = _load()


def test_prune_drops_empty_keeps_falsey_signal() -> None:
    pruned = slack_api._prune(
        {
            "id": "C1",
            "name": "",
            "is_private": False,
            "members": 0,
            "topic": None,
            "tags": [],
            "meta": {},
            "nested": {"keep": "x", "drop": None},
            "list": [{"a": 1, "b": ""}],
        }
    )
    assert pruned == {
        "id": "C1",
        "is_private": False,
        "members": 0,
        "nested": {"keep": "x"},
        "list": [{"a": 1}],
    }


def test_paginate_accumulates_across_cursors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {
            "ok": True,
            "channels": [{"id": "C1"}],
            "response_metadata": {"next_cursor": "abc"},
        },
        {"ok": True, "channels": [{"id": "C2"}], "response_metadata": {}},
    ]
    calls: list[dict[str, Any]] = []

    def fake_call(_method: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append(body)
        return pages[len(calls) - 1]

    monkeypatch.setattr(slack_api, "_call", fake_call)

    out = slack_api._paginate("conversations.list", {}, "channels", limit=200)

    assert out == {
        "ok": True,
        "channels": [{"id": "C1"}, {"id": "C2"}],
        "count": 2,
        "truncated": False,
    }
    assert calls[1]["cursor"] == "abc"  # cursor threaded through


def test_paginate_respects_limit_and_marks_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_call(_method: str, _body: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "members": [{"id": "U1"}, {"id": "U2"}, {"id": "U3"}],
            "response_metadata": {"next_cursor": "more"},
        }

    monkeypatch.setattr(slack_api, "_call", fake_call)

    out = slack_api._paginate("users.list", {}, "members", limit=2)

    assert out["count"] == 2
    assert out["members"] == [{"id": "U1"}, {"id": "U2"}]
    assert out["truncated"] is True


def test_paginate_passes_slack_error_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        slack_api,
        "_call",
        lambda *_a, **_k: {"ok": False, "error": "missing_scope"},
    )

    out = slack_api._paginate("conversations.list", {}, "channels", limit=200)

    assert out == {"ok": False, "error": "missing_scope"}
