import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.connector import (
    GithubConnector,
    GithubConnectorStage,
    _is_indexable_path,
)
from onyx.connectors.github.models import (
    GitHubFileContent,
    GitHubGitTree,
    GitHubRepository,
    GitHubTreeEntry,
)
from onyx.connectors.github.source_operations import GitHubApiError
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.mark.parametrize(
    "path,size,expected",
    [
        ("README.md", 100, True),
        ("docs/guide.mdx", 100, True),
        ("notes.txt", 100, True),
        ("manual.rst", 100, True),
        # disallowed extension (source code is intentionally excluded)
        ("main.py", 100, False),
        ("logo.png", 100, False),
        # data / config / log formats are excluded (not "documents")
        ("data.json", 100, False),
        ("table.csv", 100, False),
        ("table.tsv", 100, False),
        ("config.yaml", 100, False),
        ("config.yml", 100, False),
        ("doc.xml", 100, False),
        ("schema.sql", 100, False),
        ("output.log", 100, False),
        ("settings.conf", 100, False),
        # oversized
        ("BIG.md", 5_000_000, False),
        # denylisted path segment
        ("node_modules/pkg/README.md", 100, False),
        (".git/config.md", 100, False),
        # size unknown is allowed (still extension-gated)
        ("README.md", None, True),
        # extensionless conventional docs (case-insensitive)
        ("README", 100, True),
        ("LICENSE", 100, True),
        ("docs/CHANGELOG", 100, True),
        ("contributing", 100, True),
        # extensionless but not a known doc filename
        ("Makefile", 100, False),
        ("Dockerfile", 100, False),
    ],
)
def test_is_indexable_path(path: str, size: int | None, expected: bool) -> None:
    assert _is_indexable_path(path, size) is expected


class FakeRepoFiles:
    """The files of one repository, served through the fake gateway."""

    def __init__(
        self,
        gateway: MagicMock,
        files: dict[str, bytes],
        truncated: bool = False,
    ) -> None:
        self.files = files
        gateway.get_git_tree.side_effect = lambda **_kwargs: GitHubGitTree(
            entries=[
                GitHubTreeEntry(path=path, type="blob", size=len(content))
                for path, content in files.items()
            ],
            truncated=truncated,
        )
        gateway.get_file_content.side_effect = self._content

    def _content(
        self, *, repo_full_name: str, path: str, ref: str
    ) -> GitHubFileContent:
        del repo_full_name, ref
        return GitHubFileContent(content=self.files[path], encoding="base64")


@pytest.fixture
def serve_files(
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
) -> Callable[..., GitHubRepository]:
    """Serves the files from the configured repository and returns it."""

    def _serve(
        files: dict[str, bytes],
        pushed_at: datetime | None = None,
        truncated: bool = False,
    ) -> GitHubRepository:
        overrides: dict[str, Any] = {}
        if pushed_at is not None:
            overrides["pushed_at"] = pushed_at.isoformat()
        repo = create_repo(**overrides)
        mock_source_operations.get_repository.return_value = repo
        FakeRepoFiles(mock_source_operations, files, truncated)
        return repo

    return _serve


@pytest.fixture
def build_files_connector(
    build_github_connector: Callable[..., GithubConnector],
) -> Callable[..., GithubConnector]:
    def _build(
        include_files: bool = True, branch: str | None = None
    ) -> GithubConnector:
        return build_github_connector(
            include_prs=False,
            include_issues=False,
            include_files=include_files,
            branch=branch,
        )

    return _build


def _all_items(outputs: list) -> list:
    items: list = []
    for o in outputs:
        items.extend(o.items)
    return items


def test_files_not_indexed_when_disabled(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector(include_files=False)
    serve_files({"README.md": b"# Hello"})

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    assert _all_items(outputs) == []
    mock_source_operations.get_git_tree.assert_not_called()


def test_files_indexed_when_enabled(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files(
        {
            "README.md": b"# Hello world",
            "docs/guide.md": b"a guide",
            "src/main.py": b"print('hi')",  # excluded extension
            "logo.png": b"\x89PNG\r\n",  # excluded extension
        }
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = sorted(d.id for d in docs)
    assert ids == [
        "https://github.com/test-org/test-repo/blob/main/README.md",
        "https://github.com/test-org/test-repo/blob/main/docs/guide.md",
    ]

    readme = next(d for d in docs if d.id.endswith("README.md"))
    assert readme.semantic_identifier == "README.md"
    assert readme.sections[0].text == "# Hello world"
    assert readme.doc_metadata is not None
    assert readme.doc_metadata["hierarchy"]["source_path"] == [
        "test-org",
        "test-repo",
        "files",
        "README.md",
    ]
    assert outputs[-1].next_checkpoint.has_more is False


def test_binary_file_yields_failure(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    # .md extension but undecodable binary content
    serve_files({"corrupt.md": b"\xff\xfe\x00\x01\x80\x81"})

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    items = _all_items(outputs)
    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)


def test_undecodable_content_yields_failure(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """GitHub sends no base64 content for some files (LFS, over 1 MB).

    This must surface as a ConnectorFailure, not an unhandled TypeError.
    """
    connector = build_files_connector()
    serve_files({"big.md": b"placeholder"})
    mock_source_operations.get_file_content.side_effect = None
    mock_source_operations.get_file_content.return_value = GitHubFileContent(
        content=None, encoding="none"
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    items = _all_items(outputs)
    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)


def test_pushed_at_gate_skips_file_stage(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files({"README.md": b"# Hello"}, pushed_at=datetime(2020, 1, 1))

    # poll window starts well after the repo's last push
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    outputs = load_everything_from_checkpoint_connector(connector, start, time.time())

    assert _all_items(outputs) == []
    mock_source_operations.get_git_tree.assert_not_called()


def test_files_paginated_across_checkpoints(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files({f"doc{i:03d}.md": f"content {i}".encode() for i in range(250)})

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    assert len(docs) == 250
    assert outputs[-1].next_checkpoint.has_more is False


def test_extensionless_docs_indexed(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files(
        {
            "README": b"top-level readme",
            "LICENSE": b"MIT",
            "Makefile": b"all:\n\tbuild",  # extensionless, not a doc -> excluded
        }
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = sorted(d.id for d in docs)
    assert ids == [
        "https://github.com/test-org/test-repo/blob/main/LICENSE",
        "https://github.com/test-org/test-repo/blob/main/README",
    ]


def test_truncated_tree_yields_failure(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files({"README.md": b"# Hi"}, truncated=True)

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    items = _all_items(outputs)
    failures = [i for i in items if isinstance(i, ConnectorFailure)]
    docs = [i for i in items if isinstance(i, Document)]
    # the enumerable file is still indexed, plus one truncation failure
    assert len(docs) == 1
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert "truncated" in failures[0].failure_message.lower()


def test_empty_repository_tree_skips_file_stage(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """GitHub returns 409 when listing the tree of an empty repository."""
    connector = build_files_connector()
    serve_files({})
    mock_source_operations.get_git_tree.side_effect = GitHubApiError(
        "409", status_code=409, github_message="Git Repository is empty."
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    assert _all_items(outputs) == []
    assert outputs[-1].next_checkpoint.has_more is False


def test_branch_override_threads_through_listing_fetching_and_urls(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector(branch="gh-pages")
    serve_files({"index.md": b"# Site home", "docs/setup.md": b"setup guide"})

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = sorted(d.id for d in docs)
    assert ids == [
        "https://github.com/test-org/test-repo/blob/gh-pages/docs/setup.md",
        "https://github.com/test-org/test-repo/blob/gh-pages/index.md",
    ]
    for doc in docs:
        assert doc.metadata.get("branch") == "gh-pages"

    # Both the tree listing and every content fetch must target the branch.
    mock_source_operations.get_git_tree.assert_called_once_with(
        repo_full_name="test-org/test-repo", ref="gh-pages"
    )
    for call in mock_source_operations.get_file_content.call_args_list:
        assert call.kwargs["ref"] == "gh-pages"


def test_default_branch_used_when_branch_unset(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector()
    serve_files({"README.md": b"# Hello"})

    load_everything_from_checkpoint_connector(connector, 0, time.time())

    mock_source_operations.get_git_tree.assert_called_once_with(
        repo_full_name="test-org/test-repo", ref="main"
    )
    for call in mock_source_operations.get_file_content.call_args_list:
        assert call.kwargs["ref"] == "main"


def test_blank_branch_normalized_to_none() -> None:
    assert GithubConnector(repo_owner="o", branch="").branch is None
    assert GithubConnector(repo_owner="o", branch="   ").branch is None
    assert GithubConnector(repo_owner="o", branch=None).branch is None
    assert GithubConnector(repo_owner="o", branch=" gh-pages ").branch == "gh-pages"


def test_resumed_checkpoint_from_other_branch_relists(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """A checkpoint resumed after the branch setting changed must re-list.

    Otherwise paths listed from the old branch pair with content fetches from
    the new branch — deleted paths fail and new-branch-only files are skipped.
    """
    connector = build_files_connector(branch="gh-pages")
    repo = serve_files({"new-only.md": b"new content"})

    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.stage = GithubConnectorStage.FILES
    checkpoint.file_paths = ["old-only.md"]  # listed from the previous branch
    checkpoint.file_paths_branch = "main"
    checkpoint.curr_page = 1

    items = list(
        connector._fetch_repo_files(
            repo,
            checkpoint,
            start=None,
            is_slim=False,
            repo_external_access=None,
        )
    )

    docs = [i for i in items if isinstance(i, Document)]
    assert [d.id for d in docs] == [
        "https://github.com/test-org/test-repo/blob/gh-pages/new-only.md"
    ]
    mock_source_operations.get_git_tree.assert_called_once_with(
        repo_full_name="test-org/test-repo", ref="gh-pages"
    )
    assert checkpoint.file_paths == ["new-only.md"]
    assert checkpoint.file_paths_branch == "gh-pages"


def test_resumed_branch_change_bypasses_pushed_at_gate(
    build_files_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """Re-listing after a branch change must ignore the pushed_at gate.

    The new branch was never indexed, so an old pushed_at must not cause the
    re-listing to be skipped with an empty path list.
    """
    connector = build_files_connector(branch="gh-pages")
    repo = serve_files({"new-only.md": b"new content"}, pushed_at=datetime(2020, 1, 1))

    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.stage = GithubConnectorStage.FILES
    checkpoint.file_paths = ["old-only.md"]  # listed from the previous branch
    checkpoint.file_paths_branch = "main"
    checkpoint.curr_page = 1

    # poll window starts well after the repo's last push
    items = list(
        connector._fetch_repo_files(
            repo,
            checkpoint,
            start=datetime(2023, 1, 1, tzinfo=timezone.utc),
            is_slim=False,
            repo_external_access=None,
        )
    )

    docs = [i for i in items if isinstance(i, Document)]
    assert [d.id for d in docs] == [
        "https://github.com/test-org/test-repo/blob/gh-pages/new-only.md"
    ]
    assert checkpoint.file_paths_branch == "gh-pages"


def test_nonexistent_branch_raises_clear_error(
    build_files_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    connector = build_files_connector(branch="no-such-branch")
    repo = serve_files({})
    mock_source_operations.get_git_tree.side_effect = GitHubApiError(
        "404", status_code=404, github_message="Not Found"
    )

    with pytest.raises(ConnectorValidationError, match="no-such-branch"):
        connector._list_indexable_files(repo)


def test_prs_disabled_404_does_not_crash_files(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """A repo with PRs disabled (mirror) returns 404 on the PR listing.

    This must skip the PRS stage rather than crash the whole connector, so
    files still get indexed.
    """
    connector = build_github_connector(
        include_prs=True, include_issues=False, include_files=True
    )
    serve_files({"README.md": b"# Hi"})
    mock_source_operations.list_pull_requests.side_effect = GitHubApiError(
        "404", status_code=404, github_message="Not Found"
    )

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    assert [d.id for d in docs] == [
        "https://github.com/test-org/test-repo/blob/main/README.md"
    ]


def test_files_paginated_with_issues_enabled_no_stage_regression(
    build_github_connector: Callable[..., GithubConnector],
    serve_files: Callable[..., GitHubRepository],
) -> None:
    """Resuming a multi-batch FILES checkpoint must not regress to ISSUES.

    With include_issues=True, the unconditional stage transitions previously
    overwrote a resumed FILES checkpoint back to ISSUES, nulling file_paths and
    re-indexing files from page 0. Each file must be indexed exactly once.
    """
    connector = build_github_connector(
        include_prs=False, include_issues=True, include_files=True
    )
    serve_files({f"doc{i:03d}.md": f"content {i}".encode() for i in range(250)})

    outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = [d.id for d in docs]
    assert len(ids) == 250
    assert len(set(ids)) == 250  # no duplicates from re-indexing page 0
    assert outputs[-1].next_checkpoint.has_more is False
