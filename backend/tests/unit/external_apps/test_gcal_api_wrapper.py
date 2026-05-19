"""Unit tests for the bundled Google Calendar wrapper's pure logic
(_prune, _paginate). Loaded by path; HTTP mocked."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_WRAPPER = (
    Path(__file__).parents[3]
    / "onyx/external_apps/skill_bundles/google_calendar/gcal_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gcal_api", _WRAPPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gcal_api = _load()


def test_prune_drops_empty_keeps_falsey_signal() -> None:
    assert gcal_api._prune(
        {"a": "", "b": None, "c": 0, "d": False, "e": [], "f": [{"g": ""}]}
    ) == {"c": 0, "d": False, "f": [{}]}


def test_paginate_accumulates_page_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {"items": [{"id": "e1"}], "nextPageToken": "t1"},
        {"items": [{"id": "e2"}]},
    ]
    seen: list[dict[str, Any]] = []

    def fake_req(
        _method: str,
        _path: str,
        params: dict[str, Any] | None = None,
        _body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seen.append(params or {})
        return pages[len(seen) - 1]

    monkeypatch.setattr(gcal_api, "_req", fake_req)

    out = gcal_api._paginate("calendars/primary/events", {}, limit=250)

    assert out == {
        "ok": True,
        "items": [{"id": "e1"}, {"id": "e2"}],
        "count": 2,
        "truncated": False,
    }
    assert seen[1]["pageToken"] == "t1"  # token threaded through


def test_paginate_respects_limit_and_marks_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gcal_api,
        "_req",
        lambda *_a, **_k: {
            "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "nextPageToken": "more",
        },
    )

    out = gcal_api._paginate("users/me/calendarList", {}, limit=2)

    assert out["count"] == 2
    assert out["items"] == [{"id": "a"}, {"id": "b"}]
    assert out["truncated"] is True
