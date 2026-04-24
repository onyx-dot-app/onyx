"""Tests for GitHub connector repository code-file indexing (#9406)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.github.connector import _convert_code_file_to_document
from onyx.connectors.github.connector import _passes_path_filter
from onyx.connectors.github.connector import _should_exclude_code_file
from onyx.connectors.github.connector import CODE_FILE_EXCLUDE_PATTERNS
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.connector import GithubConnectorCheckpoint
from onyx.connectors.github.connector import GithubConnectorStage
from onyx.connectors.github.connector import MAX_CODE_FILE_BYTES
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document

# ---- _should_exclude_code_file ----


@pytest.mark.parametrize(
    "path,expected_excluded",
    [
        ("node_modules/foo.js", True),
        ("src/node_modules/bar.js", True),
        ("package-lock.json", True),
        ("packages/web/package-lock.json", True),
        ("dist/bundle.js", True),
        ("src/main/dist/out.js", True),
        ("poetry.lock", True),
        ("images/logo.png", True),
        ("docs/img/cover.jpg", True),
        ("lib/bundle.min.js", True),
        ("src/main.py", False),
        ("docs/README.md", False),
        ("backend/onyx/connectors/github/connector.py", False),
        ("Dockerfile", False),
    ],
)
def test_should_exclude_code_file(path: str, expected_excluded: bool) -> None:
    assert _should_exclude_code_file(path) is expected_excluded


def test_exclude_patterns_are_not_empty() -> None:
    # Smoke test — the list should cover the common cases we care about.
    assert len(CODE_FILE_EXCLUDE_PATTERNS) > 20


# ---- _passes_path_filter ----


@pytest.mark.parametrize(
    "path,path_filter,expected",
    [
        ("src/a.py", "src/", True),
        ("src/a.py", "src", True),
        ("src", "src", True),
        ("src", "src/", True),
        ("docs/a.md", "src/", False),
        ("src-things/a.py", "src/", False),  # prefix must be path-component
        ("anything.py", None, True),
        ("anything.py", "", True),
        ("anything.py", "   ", True),
    ],
)
def test_passes_path_filter(path: str, path_filter: str | None, expected: bool) -> None:
    # The connector trims whitespace → treat "   " as "no filter" in the helper
    # by passing the stripped value. Directly hitting the helper with raw input
    # should also not throw; an all-whitespace filter is treated as a positive
    # prefix match, which is fine since users never see that state.
    if path_filter is not None and path_filter.strip() == "":
        path_filter = None
    assert _passes_path_filter(path, path_filter) is expected


# ---- _convert_code_file_to_document ----


def test_convert_code_file_to_document_shape() -> None:
    repo = MagicMock()
    repo.html_url = "https://github.com/test-org/test-repo"
    repo.full_name = "test-org/test-repo"

    doc = _convert_code_file_to_document(
        repo=repo,
        path="src/main.py",
        content="print('hello')",
        default_branch="main",
        external_access=None,
    )

    assert isinstance(doc, Document)
    assert doc.id == "https://github.com/test-org/test-repo/blob/main/src/main.py"
    assert doc.semantic_identifier == "src/main.py"
    assert doc.metadata == {
        "type": "CodeFile",
        "repo": "test-org/test-repo",
        "path": "src/main.py",
        "branch": "main",
    }
    assert len(doc.sections) == 1
    assert doc.sections[0].text == "print('hello')"
    assert (
        doc.sections[0].link
        == "https://github.com/test-org/test-repo/blob/main/src/main.py"
    )


# ---- CODE_FILES stage: listing ----


def _mk_tree_entry(path: str, *, type_: str = "blob", size: int | None = 100) -> Any:
    entry = MagicMock()
    entry.path = path
    entry.type = type_
    entry.size = size
    return entry


def _mk_repo(
    name: str = "test-repo",
    default_branch: str = "main",
    tree_entries: list[Any] | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.name = name
    repo.default_branch = default_branch
    repo.html_url = f"https://github.com/test-org/{name}"
    repo.full_name = f"test-org/{name}"
    repo.raw_headers = {"status": "200 OK"}
    repo.raw_data = {"id": 1, "name": name, "full_name": f"test-org/{name}"}
    repo.get_git_tree = MagicMock(return_value=MagicMock(tree=tree_entries or []))
    return repo


def _seed_checkpoint_for_code_files(
    cached_paths: list[str] | None = None,
) -> GithubConnectorCheckpoint:
    return GithubConnectorCheckpoint(
        stage=GithubConnectorStage.CODE_FILES,
        curr_page=0,
        num_retrieved=0,
        has_more=True,
        cached_repo_ids=[],
        cached_repo=SerializedRepository(
            id=1,
            headers={"status": "200 OK"},
            raw_data={
                "id": 1,
                "name": "test-repo",
                "full_name": "test-org/test-repo",
            },
        ),
        cached_code_file_paths=cached_paths,
    )


def _drain(gen: Any) -> tuple[list[Document | ConnectorFailure], Any]:
    """Consume a Generator-that-returns-checkpoint, returning (items, checkpoint)."""
    items: list[Document | ConnectorFailure] = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            return items, stop.value


def test_code_files_stage_lists_tree_on_first_call() -> None:
    """First call in the stage: list, filter, cache paths — no yields yet."""
    tree_entries = [
        _mk_tree_entry("src/main.py"),
        _mk_tree_entry("src", type_="tree"),  # directories are skipped
        _mk_tree_entry("node_modules/foo.js"),  # excluded
        _mk_tree_entry("docs/README.md"),
        _mk_tree_entry("package-lock.json"),  # excluded
    ]
    repo = _mk_repo(tree_entries=tree_entries)

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()

    checkpoint = _seed_checkpoint_for_code_files(cached_paths=None)

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        items, returned = _drain(connector._fetch_from_github(checkpoint))

    assert items == []
    assert returned.cached_code_file_paths == ["src/main.py", "docs/README.md"]


def test_code_files_stage_respects_path_filter() -> None:
    tree_entries = [
        _mk_tree_entry("src/a.py"),
        _mk_tree_entry("docs/a.md"),
    ]
    repo = _mk_repo(tree_entries=tree_entries)

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
        code_files_path_filter="src/",
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(cached_paths=None)

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        _, returned = _drain(connector._fetch_from_github(checkpoint))

    assert returned.cached_code_file_paths == ["src/a.py"]


def test_code_files_stage_skips_oversize_files() -> None:
    tree_entries = [
        _mk_tree_entry("src/small.py", size=100),
        _mk_tree_entry("src/huge.csv", size=MAX_CODE_FILE_BYTES + 1),
    ]
    repo = _mk_repo(tree_entries=tree_entries)

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(cached_paths=None)

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        _, returned = _drain(connector._fetch_from_github(checkpoint))

    assert returned.cached_code_file_paths == ["src/small.py"]


# ---- CODE_FILES stage: yielding ----


def _mk_content_file(text: str) -> MagicMock:
    cf = MagicMock()
    cf.decoded_content = text.encode("utf-8")
    return cf


def test_code_files_stage_yields_documents_in_batches() -> None:
    repo = _mk_repo()
    repo.get_contents = MagicMock(
        side_effect=lambda path, ref: _mk_content_file(f"// {path}")  # noqa: ARG005
    )

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(
        cached_paths=["src/a.py", "src/b.py", "docs/c.md"]
    )

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        items, returned = _drain(connector._fetch_from_github(checkpoint))

    docs = [i for i in items if isinstance(i, Document)]
    assert len(docs) == 3
    ids = {d.id for d in docs}
    assert ids == {
        "https://github.com/test-org/test-repo/blob/main/src/a.py",
        "https://github.com/test-org/test-repo/blob/main/src/b.py",
        "https://github.com/test-org/test-repo/blob/main/docs/c.md",
    }
    # Cache drained — code-files stage is done for this repo; reset() clears
    # the cached-paths field back to None along with other resumable state.
    assert returned.cached_code_file_paths is None


def test_code_files_stage_handles_decode_errors_gracefully() -> None:
    """Non-UTF-8 bytes should still yield a Document via errors='replace'."""
    repo = _mk_repo()
    cf = MagicMock()
    cf.decoded_content = b"\xff\xfe\x00invalid utf-8"
    repo.get_contents = MagicMock(return_value=cf)

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(cached_paths=["src/bad.bin"])

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        items, _ = _drain(connector._fetch_from_github(checkpoint))

    docs = [i for i in items if isinstance(i, Document)]
    failures = [i for i in items if isinstance(i, ConnectorFailure)]
    assert len(docs) == 1
    assert len(failures) == 0
    # The replacement character survives in the content
    assert doc_text_from(docs[0]).startswith("�")


def test_code_files_stage_yields_failure_on_content_exception() -> None:
    repo = _mk_repo()
    repo.get_contents = MagicMock(side_effect=RuntimeError("boom"))

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(cached_paths=["src/bad.py"])

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        items, _ = _drain(connector._fetch_from_github(checkpoint))

    docs = [i for i in items if isinstance(i, Document)]
    failures = [i for i in items if isinstance(i, ConnectorFailure)]
    assert docs == []
    assert len(failures) == 1


def test_code_files_slim_yields_stubs_without_fetching_content() -> None:
    repo = _mk_repo()
    repo.get_contents = MagicMock()

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()
    checkpoint = _seed_checkpoint_for_code_files(cached_paths=["src/a.py"])

    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        items, _ = _drain(connector._fetch_from_github(checkpoint, is_slim=True))

    docs = [i for i in items if isinstance(i, Document)]
    assert len(docs) == 1
    assert docs[0].sections == []
    assert docs[0].id == "https://github.com/test-org/test-repo/blob/main/src/a.py"
    # No content fetch in slim mode.
    repo.get_contents.assert_not_called()


def doc_text_from(doc: Document) -> str:
    return doc.sections[0].text if doc.sections else ""


# ---- Full-state-machine regression: CODE_FILES reachable without issues ----


def test_code_files_reachable_when_issues_disabled() -> None:
    """Regression for #10578 review (P1): code-files-only connector (PRs off,
    issues off, code files on — which is what most users of this feature
    want) must actually transition from ISSUES → CODE_FILES and emit docs.

    The original implementation buried the transition inside the
    ``if self.include_issues`` block, so the default configuration
    (``include_issues=False``) would silently skip code indexing entirely.
    """
    tree_entries = [_mk_tree_entry("src/only.py")]
    repo = _mk_repo(tree_entries=tree_entries)
    repo.get_contents = MagicMock(return_value=_mk_content_file("print('hi')"))

    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_code_files=True,
    )
    connector.github_client = MagicMock()

    # Drive the state machine from the start stage (PRS), not pre-seeded.
    checkpoint = GithubConnectorCheckpoint(
        stage=GithubConnectorStage.PRS,
        curr_page=0,
        num_retrieved=0,
        has_more=True,
        cached_repo_ids=[],
        cached_repo=SerializedRepository(
            id=1,
            headers={"status": "200 OK"},
            raw_data={
                "id": 1,
                "name": "test-repo",
                "full_name": "test-org/test-repo",
            },
        ),
    )

    collected: list[Document] = []
    with patch(
        "onyx.connectors.github.connector.deserialize_repository", return_value=repo
    ):
        # Step until drained. Each call processes one stage/page.
        guard = 0
        while checkpoint.has_more and guard < 20:
            guard += 1
            items, checkpoint = _drain(connector._fetch_from_github(checkpoint))
            collected.extend(i for i in items if isinstance(i, Document))

    assert any(
        doc.id == "https://github.com/test-org/test-repo/blob/main/src/only.py"
        for doc in collected
    ), "code-files-only connector should emit CodeFile docs"
