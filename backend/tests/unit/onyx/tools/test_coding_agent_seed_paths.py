from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

from onyx.configs.constants import (
    CODE_FILE_METADATA_TYPE,
    CODE_FILE_PATH_KEY,
    CODE_FILE_REPO_KEY,
    CODE_FILE_TYPE_KEY,
)
from onyx.repo_archives.github import GitHubArchiveProvider
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)

ONYX_REPO = GitHubArchiveProvider.repo_ref("onyx-dot-app", "onyx")


def _chunk(repo: str, path: Any) -> SimpleNamespace:
    return SimpleNamespace(
        metadata={CODE_FILE_REPO_KEY: repo, CODE_FILE_PATH_KEY: path}
    )


@contextmanager
def _seed_path_mocks(chunks: list[SimpleNamespace]) -> Iterator[MagicMock]:
    document_index = MagicMock()
    document_index.keyword_retrieval.return_value = chunks
    with (
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
            MagicMock(), "some query", ONYX_REPO, limit=2
        )
    assert paths == ["a.py", "b.py"]


def test_seed_paths_restrict_retrieval_to_code_files() -> None:
    """PRs/issues/docs share the repo metadata key, so the index filter must
    keep the retrieval budget on source-code chunks."""
    with _seed_path_mocks([]) as document_index:
        CodingAgentTool._fetch_seed_paths(MagicMock(), "query", ONYX_REPO)

    filters = document_index.keyword_retrieval.call_args.kwargs["filters"]
    assert filters.tags is not None
    assert [(tag.tag_key, tag.tag_value) for tag in filters.tags] == [
        (CODE_FILE_TYPE_KEY, CODE_FILE_METADATA_TYPE)
    ]


def test_seed_paths_failure_degrades_to_empty() -> None:
    with patch(
        "onyx.db.search_settings.get_current_search_settings",
        side_effect=RuntimeError("db down"),
    ):
        paths = CodingAgentTool._fetch_seed_paths(MagicMock(), "query", ONYX_REPO)
    assert paths == []
