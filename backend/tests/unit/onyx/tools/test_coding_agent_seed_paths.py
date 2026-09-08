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

ONYX_REPO = GitHubArchiveProvider.repo_ref_from_url("onyx-dot-app/onyx")

_ACCESS_FILTERS_FN = (
    "onyx.context.search.preprocessing.access_filters.build_access_filters_for_user"
)


def _tool(user: Any = None) -> CodingAgentTool:
    return CodingAgentTool(
        tool_id=1,
        emitter=MagicMock(),
        llm=MagicMock(),
        user=user if user is not None else MagicMock(),
    )


def _chunk(repo: str, path: Any) -> SimpleNamespace:
    return SimpleNamespace(
        metadata={CODE_FILE_REPO_KEY: repo, CODE_FILE_PATH_KEY: path}
    )


@contextmanager
def _seed_path_mocks(
    chunks: list[SimpleNamespace], acl: list[str] | None = None
) -> Iterator[MagicMock]:
    document_index = MagicMock()
    document_index.keyword_retrieval.return_value = chunks
    with (
        patch("onyx.db.search_settings.get_current_search_settings"),
        patch(
            "onyx.document_index.factory.get_default_document_index",
            return_value=document_index,
        ),
        patch(_ACCESS_FILTERS_FN, return_value=acl if acl is not None else []),
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
        paths = _tool()._fetch_seed_paths(MagicMock(), "some query", ONYX_REPO, limit=2)
    assert paths == ["a.py", "b.py"]


def test_seed_paths_restrict_retrieval_to_code_files() -> None:
    """PRs/issues/docs share the repo metadata key, so the index filter must
    keep the retrieval budget on source-code chunks."""
    with _seed_path_mocks([]) as document_index:
        _tool()._fetch_seed_paths(MagicMock(), "query", ONYX_REPO)

    filters = document_index.keyword_retrieval.call_args.kwargs["filters"]
    assert filters.tags is not None
    assert [(tag.tag_key, tag.tag_value) for tag in filters.tags] == [
        (CODE_FILE_TYPE_KEY, CODE_FILE_METADATA_TYPE)
    ]


def test_seed_paths_apply_the_users_access_filters() -> None:
    """Seeding is an ordinary index read. It must go through the same ACL as
    every other tool, not a bypass justified by some other check."""
    user = MagicMock()
    db_session = MagicMock()

    with _seed_path_mocks([], acl=["acl-entry"]) as document_index:
        with patch(_ACCESS_FILTERS_FN, return_value=["acl-entry"]) as build_filters:
            _tool(user)._fetch_seed_paths(db_session, "query", ONYX_REPO)

    build_filters.assert_called_once_with(user, db_session)
    filters = document_index.keyword_retrieval.call_args.kwargs["filters"]
    assert filters.access_control_list == ["acl-entry"]


def test_seed_paths_failure_degrades_to_empty() -> None:
    with patch(
        "onyx.db.search_settings.get_current_search_settings",
        side_effect=RuntimeError("db down"),
    ):
        paths = _tool()._fetch_seed_paths(MagicMock(), "query", ONYX_REPO)
    assert paths == []
