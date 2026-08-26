import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from github.GithubException import GithubException, UnknownObjectException

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.connector import (
    GithubConnector,
    GithubConnectorStage,
    _is_indexable_path,
)
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.models import (
    CodeSection,
    ConnectorFailure,
    Document,
    TextSection,
)
from tests.unit.onyx.connectors.github.conftest import make_mock_repo
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


@pytest.mark.parametrize(
    "path,size,expected",
    [
        # source code is included when the flag is on
        ("main.py", 100, True),
        ("src/app.tsx", 100, True),
        ("native/lib.cpp", 100, True),
        ("schema.sql", 100, True),
        # config formats magika classifies as code are included too
        ("data.json", 100, True),
        ("config.yaml", 100, True),
        # non-code stays excluded
        ("logo.png", 100, False),
        ("secrets.env", 100, False),
        ("key.pem", 100, False),
        # size cap and denylist still apply to code
        ("huge.py", 5_000_000, False),
        ("node_modules/pkg/index.js", 100, False),
        ("target/debug/gen.rs", 100, False),
        ("web/.next/static/chunk.js", 100, False),
        ("coverage/lcov-report/index.js", 100, False),
        # generated files are code, and are still not worth indexing
        ("package-lock.json", 100, False),
        ("Cargo.lock", 100, False),
        ("static/jquery.min.js", 100, False),
        # docs still included alongside code
        ("README.md", 100, True),
    ],
)
def test_is_indexable_path_with_code_files(
    path: str, size: int | None, expected: bool
) -> None:
    assert _is_indexable_path(path, size, include_code_files=True) is expected


def test_is_indexable_path_code_only_excludes_docs() -> None:
    assert (
        _is_indexable_path(
            "README.md", 100, include_docs=False, include_code_files=True
        )
        is False
    )
    assert (
        _is_indexable_path("main.py", 100, include_docs=False, include_code_files=True)
        is True
    )


@pytest.fixture(autouse=True)
def no_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the API fetching path; snapshot-based fetching is
    covered in test_github_snapshot_stage.py."""

    def _no_snapshot(self: GithubConnector, repo: object) -> None:
        del self, repo
        return None

    monkeypatch.setattr(GithubConnector, "_ensure_snapshot", _no_snapshot)


@pytest.fixture
def create_mock_repo() -> Callable[..., MagicMock]:
    def _create(
        files: dict[str, bytes],
        pushed_at: datetime | None = None,
        truncated: bool = False,
    ) -> MagicMock:
        return make_mock_repo(files=files, pushed_at=pushed_at, truncated=truncated)

    return _create


def _build_connector(
    mock_github_client: MagicMock,
    include_files: bool = True,
    include_code_files: bool = False,
    branch: str | None = None,
) -> GithubConnector:
    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_files=include_files,
        include_code_files=include_code_files,
        branch=branch,
    )
    connector.github_client = mock_github_client
    return connector


def _all_items(outputs: list) -> list:
    items: list = []
    for o in outputs:
        items.extend(o.items)
    return items


def test_files_not_indexed_when_disabled(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client, include_files=False)
    mock_repo = create_mock_repo({"README.md": b"# Hello"})
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    assert _all_items(outputs) == []
    mock_repo.get_git_tree.assert_not_called()


def test_files_indexed_when_enabled(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo(
        {
            "README.md": b"# Hello world",
            "docs/guide.md": b"a guide",
            "src/main.py": b"print('hi')",  # excluded extension
            "logo.png": b"\x89PNG\r\n",  # excluded extension
        }
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
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


def test_code_files_indexed_as_code_sections(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client, include_code_files=True)
    mock_repo = create_mock_repo(
        {
            "README.md": b"# Hello world",
            "src/main.py": b"print('hi')",
        }
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    assert sorted(d.semantic_identifier for d in docs) == [
        "README.md",
        "src/main.py",
    ]

    code_doc = next(d for d in docs if d.semantic_identifier == "src/main.py")
    code_section = code_doc.sections[0]
    assert isinstance(code_section, CodeSection)
    assert code_section.language == "python"
    assert code_section.file_path == "src/main.py"
    assert code_section.text == "print('hi')"
    assert code_doc.metadata["type"] == "CodeFile"
    assert code_doc.metadata["language"] == "python"

    readme_doc = next(d for d in docs if d.semantic_identifier == "README.md")
    assert isinstance(readme_doc.sections[0], TextSection)
    assert "type" not in readme_doc.metadata


def test_code_files_excluded_when_flag_off(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(
        mock_github_client, include_files=False, include_code_files=True
    )
    mock_repo = create_mock_repo(
        {
            "README.md": b"# Hello world",
            "src/main.py": b"print('hi')",
        }
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    # Docs off + code on: only the code file is indexed.
    assert [d.semantic_identifier for d in docs] == ["src/main.py"]


def test_binary_file_yields_failure(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    # .md extension but undecodable binary content
    mock_repo = create_mock_repo({"corrupt.md": b"\xff\xfe\x00\x01\x80\x81"})
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    items = _all_items(outputs)
    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)


def test_undecodable_content_yields_failure(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """decoded_content is None for non-base64 encodings (LFS, encoding='none').

    This must surface as a ConnectorFailure, not an unhandled TypeError.
    """
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo({"big.md": b"placeholder"})

    none_content = MagicMock()
    none_content.decoded_content = None
    none_content.encoding = "none"
    mock_repo.get_contents = MagicMock(return_value=none_content)
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    items = _all_items(outputs)
    assert len(items) == 1
    assert isinstance(items[0], ConnectorFailure)


def test_pushed_at_gate_skips_file_stage(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo(
        {"README.md": b"# Hello"},
        pushed_at=datetime(2020, 1, 1),
    )
    mock_github_client.get_repo.return_value = mock_repo

    # poll window starts well after the repo's last push
    start = datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp()
    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(
            connector, start, time.time()
        )

    assert _all_items(outputs) == []
    mock_repo.get_git_tree.assert_not_called()


def test_files_paginated_across_checkpoints(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    files = {f"doc{i:03d}.md": f"content {i}".encode() for i in range(250)}
    mock_repo = create_mock_repo(files)
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    assert len(docs) == 250
    assert outputs[-1].next_checkpoint.has_more is False


def test_extensionless_docs_indexed(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo(
        {
            "README": b"top-level readme",
            "LICENSE": b"MIT",
            "Makefile": b"all:\n\tbuild",  # extensionless, not a doc -> excluded
        }
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = sorted(d.id for d in docs)
    assert ids == [
        "https://github.com/test-org/test-repo/blob/main/LICENSE",
        "https://github.com/test-org/test-repo/blob/main/README",
    ]


def test_truncated_tree_yields_failure(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo({"README.md": b"# Hi"}, truncated=True)
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
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
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """GitHub returns 409 when listing the tree of an empty repository."""
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo({})
    mock_repo.get_git_tree.side_effect = GithubException(
        409, {"message": "Git Repository is empty."}, {}
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    assert _all_items(outputs) == []
    assert outputs[-1].next_checkpoint.has_more is False


def test_branch_override_threads_through_listing_fetching_and_urls(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client, branch="gh-pages")
    mock_repo = create_mock_repo(
        {
            "index.md": b"# Site home",
            "docs/setup.md": b"setup guide",
        }
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
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
    mock_repo.get_git_tree.assert_called_once_with("gh-pages", recursive=True)
    for call in mock_repo.get_contents.call_args_list:
        assert call.kwargs["ref"] == "gh-pages"


def test_default_branch_used_when_branch_unset(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client)
    mock_repo = create_mock_repo({"README.md": b"# Hello"})
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        load_everything_from_checkpoint_connector(connector, 0, time.time())

    mock_repo.get_git_tree.assert_called_once_with("main", recursive=True)
    for call in mock_repo.get_contents.call_args_list:
        assert call.kwargs["ref"] == "main"


def test_blank_branch_normalized_to_none() -> None:
    assert GithubConnector(repo_owner="o", branch="").branch is None
    assert GithubConnector(repo_owner="o", branch="   ").branch is None
    assert GithubConnector(repo_owner="o", branch=None).branch is None
    assert GithubConnector(repo_owner="o", branch=" gh-pages ").branch == "gh-pages"


def test_resumed_checkpoint_from_other_branch_relists(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """A checkpoint resumed after the branch setting changed must re-list.

    Otherwise paths listed from the old branch pair with content fetches from
    the new branch — deleted paths fail and new-branch-only files are skipped.
    """
    connector = _build_connector(mock_github_client, branch="gh-pages")
    mock_repo = create_mock_repo({"new-only.md": b"new content"})

    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.stage = GithubConnectorStage.FILES
    checkpoint.file_paths = ["old-only.md"]  # listed from the previous branch
    checkpoint.file_paths_branch = "main"
    checkpoint.curr_page = 1

    items = list(
        connector._fetch_repo_files(
            mock_repo,
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
    mock_repo.get_git_tree.assert_called_once_with("gh-pages", recursive=True)
    assert checkpoint.file_paths == ["new-only.md"]
    assert checkpoint.file_paths_branch == "gh-pages"


def test_resumed_checkpoint_relists_when_code_indexing_is_toggled(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Turning code indexing on changes what the listing contains, so a
    checkpoint listed under the old setting has to be discarded like one
    listed from another branch."""
    connector = _build_connector(mock_github_client, include_code_files=True)
    mock_repo = create_mock_repo({"README.md": b"docs", "main.py": b"code"})

    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.stage = GithubConnectorStage.FILES
    checkpoint.file_paths = ["README.md"]  # listed with code indexing off
    checkpoint.file_paths_include_code = False
    checkpoint.file_paths_branch = connector._resolve_branch(mock_repo)

    list(
        connector._fetch_repo_files(
            mock_repo,
            checkpoint,
            start=None,
            is_slim=False,
            repo_external_access=None,
        )
    )

    assert sorted(checkpoint.file_paths or []) == ["README.md", "main.py"]
    assert checkpoint.file_paths_include_code is True


def test_resumed_branch_change_bypasses_pushed_at_gate(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Re-listing after a branch change must ignore the pushed_at gate.

    The new branch was never indexed, so an old pushed_at must not cause the
    re-listing to be skipped with an empty path list.
    """
    connector = _build_connector(mock_github_client, branch="gh-pages")
    mock_repo = create_mock_repo(
        {"new-only.md": b"new content"},
        pushed_at=datetime(2020, 1, 1),
    )

    checkpoint = connector.build_dummy_checkpoint()
    checkpoint.stage = GithubConnectorStage.FILES
    checkpoint.file_paths = ["old-only.md"]  # listed from the previous branch
    checkpoint.file_paths_branch = "main"
    checkpoint.curr_page = 1

    # poll window starts well after the repo's last push
    items = list(
        connector._fetch_repo_files(
            mock_repo,
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
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    connector = _build_connector(mock_github_client, branch="no-such-branch")
    mock_repo = create_mock_repo({})
    mock_repo.get_git_tree.side_effect = GithubException(
        404, {"message": "Not Found"}, {}
    )

    with pytest.raises(ConnectorValidationError, match="no-such-branch"):
        connector._list_indexable_files(mock_repo)


def test_prs_disabled_404_does_not_crash_files(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """A repo with PRs disabled (mirror) returns 404 on get_pulls.

    This must skip the PRS stage rather than crash the whole connector, so
    files still get indexed.
    """
    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=True,
        include_issues=False,
        include_files=True,
    )
    connector.github_client = mock_github_client

    mock_repo = create_mock_repo({"README.md": b"# Hi"})
    mock_repo.get_pulls.return_value.get_page.side_effect = UnknownObjectException(
        404, {"message": "Not Found"}, {}
    )
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    assert [d.id for d in docs] == [
        "https://github.com/test-org/test-repo/blob/main/README.md"
    ]


def test_files_paginated_with_issues_enabled_no_stage_regression(
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
) -> None:
    """Resuming a multi-batch FILES checkpoint must not regress to ISSUES.

    With include_issues=True, the unconditional stage transitions previously
    overwrote a resumed FILES checkpoint back to ISSUES, nulling file_paths and
    re-indexing files from page 0. Each file must be indexed exactly once.
    """
    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=True,
        include_files=True,
    )
    connector.github_client = mock_github_client

    files = {f"doc{i:03d}.md": f"content {i}".encode() for i in range(250)}
    mock_repo = create_mock_repo(files)
    mock_repo.get_issues.return_value.get_page.return_value = []  # no issues
    mock_github_client.get_repo.return_value = mock_repo

    with patch.object(SerializedRepository, "to_Repository", return_value=mock_repo):
        outputs = load_everything_from_checkpoint_connector(connector, 0, time.time())

    docs = [i for i in _all_items(outputs) if isinstance(i, Document)]
    ids = [d.id for d in docs]
    assert len(ids) == 250
    assert len(set(ids)) == 250  # no duplicates from re-indexing page 0
    assert outputs[-1].next_checkpoint.has_more is False


def test_connector_accepts_full_connector_specific_config() -> None:
    """`instantiate_connector` splats connector_specific_config into __init__
    unfiltered, so every key the admin form saves must be accepted."""
    config: dict[str, Any] = {
        "repo_owner": "test-org",
        "repositories": "test-repo",
        "include_prs": True,
        "include_issues": False,
        "include_files": True,
        "include_code_files": True,
        "branch": "main",
    }

    connector = GithubConnector(**config)

    assert connector.include_code_files is True
