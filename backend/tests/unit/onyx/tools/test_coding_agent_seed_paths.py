from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)


def _chunk(repo: str, path: Any) -> SimpleNamespace:
    return SimpleNamespace(metadata={"repo": repo, "path": path})


@contextmanager
def _seed_path_mocks(chunks: list[SimpleNamespace]) -> Iterator[MagicMock]:
    document_index = MagicMock()
    document_index.keyword_retrieval.return_value = chunks
    with (
        patch(
            "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
            ".get_session_with_current_tenant"
        ),
        patch("onyx.db.search_settings.get_current_search_settings"),
        patch(
            "onyx.document_index.factory.get_default_document_index",
            return_value=document_index,
        ),
    ):
        yield document_index


def test_seed_paths_filter_dedupe_and_cap() -> None:
    chunks = [
        _chunk("onyx-dot-app/onyx", "a.py"),
        _chunk("other-org/other", "not-our-repo.py"),
        _chunk("Onyx-Dot-App/Onyx", "b.py"),  # repo match is case-insensitive
        _chunk("onyx-dot-app/onyx", "a.py"),  # duplicate path dropped
        _chunk("onyx-dot-app/onyx", ["list.py"]),  # non-str path skipped
        _chunk("onyx-dot-app/onyx", "c.py"),
    ]
    with _seed_path_mocks(chunks):
        paths = CodingAgentTool._fetch_seed_paths(
            "some query", "onyx-dot-app/onyx", limit=2
        )
    assert paths == ["a.py", "b.py"]


def test_seed_paths_failure_degrades_to_empty() -> None:
    with (
        patch(
            "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
            ".get_session_with_current_tenant",
            side_effect=RuntimeError("db down"),
        ),
    ):
        paths = CodingAgentTool._fetch_seed_paths("query", "onyx-dot-app/onyx")
    assert paths == []


def test_seed_paths_unparseable_repo_degrades_to_empty() -> None:
    with _seed_path_mocks([]):
        paths = CodingAgentTool._fetch_seed_paths("query", "not a repo url %%%")
    assert paths == []
