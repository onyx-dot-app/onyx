"""Unit tests for the bundled Linear wrapper's pure logic (_prune,
_paginate). Loaded by path; HTTP mocked — never touches the network."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_WRAPPER = (
    Path(__file__).parents[3] / "onyx/external_apps/skill_bundles/linear/linear_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("linear_api", _WRAPPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


linear_api = _load()


def test_prune_drops_empty_keeps_falsey_signal() -> None:
    assert linear_api._prune(
        {"a": "", "b": None, "c": 0, "d": False, "e": {"x": "", "y": 1}}
    ) == {"c": 0, "d": False, "e": {"y": 1}}


def test_paginate_walks_graphql_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {
            "data": {
                "issues": {
                    "nodes": [{"id": "1"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
                }
            }
        },
        {
            "data": {
                "issues": {
                    "nodes": [{"id": "2"}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        },
    ]
    seen: list[dict[str, Any]] = []

    def fake_gql(_query: str, variables: dict[str, Any]) -> dict[str, Any]:
        seen.append(variables)
        return pages[len(seen) - 1]

    monkeypatch.setattr(linear_api, "_gql", fake_gql)

    out = linear_api._paginate("q", {}, "issues", limit=100)

    assert out == {
        "ok": True,
        "issues": [{"id": "1"}, {"id": "2"}],
        "count": 2,
        "truncated": False,
    }
    assert seen[1]["after"] == "c1"  # cursor threaded through


def test_paginate_respects_limit_and_marks_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        linear_api,
        "_gql",
        lambda *_a, **_k: {
            "data": {
                "teams": {
                    "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "x"},
                }
            }
        },
    )

    out = linear_api._paginate("q", {}, "teams", limit=2)

    assert out["count"] == 2
    assert out["teams"] == [{"id": "A"}, {"id": "B"}]
    assert out["truncated"] is True


def test_paginate_passes_graphql_errors_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        linear_api,
        "_gql",
        lambda *_a, **_k: {"errors": [{"message": "bad"}]},
    )

    out = linear_api._paginate("q", {}, "issues", limit=100)

    assert out == {"ok": False, "errors": [{"message": "bad"}]}
