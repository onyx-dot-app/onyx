"""Code-file behaviour of the GitLab connector.

The connector used to walk the whole repository on every poll and stamp each
file with the fetch time. The indexing pipeline reads an advanced
`doc_updated_at` as proof of change and then skips its content hash gate, so
every file was re-chunked and re-embedded on every poll. These tests pin the two
fixes: a poll only yields files that commits in the window touched, and no code
file ever carries a fetch-time stamp.
"""

import itertools
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from gitlab.exceptions import GitlabError, GitlabGetError

from onyx.connectors.gitlab.connector import MAX_POLL_COMMITS, GitlabConnector
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.models import Document

WINDOW_START = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
COMMIT_TIME = "2026-09-05T11:00:00.000+00:00"
DEFAULT_BRANCH = "main"


def _blob(path: str, blob_id: str) -> dict[str, str]:
    return {"id": blob_id, "name": path.split("/")[-1], "path": path, "type": "blob"}


def _tree(path: str) -> dict[str, str]:
    return {"id": f"tree-{path}", "name": path, "path": path, "type": "tree"}


def _file_object(blob_id: str, path: str, content: bytes = b"file body") -> MagicMock:
    obj = MagicMock()
    obj.blob_id = blob_id
    obj.file_name = path.split("/")[-1]
    obj.file_path = path
    obj.decode.return_value = content
    return obj


def _commit(
    diffs: list[dict[str, Any]], committed_date: str = COMMIT_TIME
) -> MagicMock:
    commit = MagicMock()
    commit.id = "abc123"
    commit.committed_date = committed_date
    commit.diff.return_value = diffs
    return commit


@pytest.fixture
def project() -> MagicMock:
    """A project whose tree holds two blobs under one subdirectory."""
    project = MagicMock()
    project.default_branch = DEFAULT_BRANCH

    tree = {
        "": [_blob("README.md", "blob-readme"), _tree("src")],
        "src": [_blob("src/app.py", "blob-app")],
    }
    project.repository_tree.side_effect = lambda path, **_kwargs: tree[path]

    blob_ids = {"README.md": "blob-readme", "src/app.py": "blob-app"}

    def _get_file(file_path: str, **_kwargs: Any) -> MagicMock:
        if file_path not in blob_ids:
            raise GitlabGetError("404 File Not Found", response_code=404)
        return _file_object(blob_ids[file_path], file_path)

    project.files.get.side_effect = _get_file
    project.commits.list.return_value = []
    return project


@pytest.fixture
def connector(project: MagicMock) -> GitlabConnector:
    connector = GitlabConnector(
        project_owner="acme",
        project_name="platform",
        batch_size=10,
        include_mrs=False,
        include_issues=False,
        include_code_files=True,
    )
    client = MagicMock()
    client.url = "https://gitlab.example.com"
    client.projects.get.return_value = project
    connector.gitlab_client = client
    return connector


def _documents(batches: GenerateDocumentsOutput) -> list[Document]:
    """Flatten batches to Documents. This connector yields no HierarchyNodes."""
    return [doc for doc in itertools.chain(*batches) if isinstance(doc, Document)]


def _poll(connector: GitlabConnector) -> list[Document]:
    return _documents(
        connector.poll_source(WINDOW_START.timestamp(), WINDOW_END.timestamp())
    )


def _walk(connector: GitlabConnector) -> list[Document]:
    return _documents(connector.load_from_state())


def test_poll_with_no_commits_yields_nothing(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """The regression that caused the bill: an idle window must cost nothing."""
    project.commits.list.return_value = []

    assert _poll(connector) == []
    # No blob content was read, so no chunk reached the embedder.
    project.files.get.assert_not_called()
    project.repository_tree.assert_not_called()


def test_poll_yields_only_changed_files_stamped_with_commit_time(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.commits.list.return_value = [
        _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    ]

    docs = _poll(connector)

    assert [doc.id for doc in docs] == ["blob-app"]
    assert docs[0].doc_updated_at == datetime(2026, 9, 5, 11, 0, tzinfo=timezone.utc)
    assert docs[0].semantic_identifier == "app.py"
    assert docs[0].sections[0].link == (
        "https://gitlab.example.com/acme/platform/-/blob/main/src/app.py"
    )
    # The untouched blob was never fetched.
    assert project.files.get.call_count == 1


def test_poll_omits_deleted_files(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """A deletion has no document to yield; pruning removes the indexed one."""
    project.commits.list.return_value = [
        _commit(
            [
                {
                    "old_path": "src/gone.py",
                    "new_path": "src/gone.py",
                    "deleted_file": True,
                },
                {"old_path": "src/app.py", "new_path": "src/app.py"},
            ]
        )
    ]

    assert [doc.id for doc in _poll(connector)] == ["blob-app"]


def test_poll_follows_a_rename_to_its_destination(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.commits.list.return_value = [
        _commit(
            [
                {
                    "old_path": "src/old_name.py",
                    "new_path": "src/app.py",
                    "renamed_file": True,
                }
            ]
        )
    ]

    assert [doc.id for doc in _poll(connector)] == ["blob-app"]


def test_poll_skips_a_blob_that_vanished_mid_poll(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """A moving branch 404s a path. That must not fail the whole attempt."""
    project.commits.list.return_value = [
        _commit(
            [
                {"new_path": "src/raced.py", "old_path": "src/raced.py"},
                {"new_path": "src/app.py", "old_path": "src/app.py"},
            ]
        )
    ]

    assert [doc.id for doc in _poll(connector)] == ["blob-app"]


def test_poll_skips_binary_blobs(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """A poll and a full walk must agree on which blobs produce a document."""
    project.commits.list.return_value = [
        _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    ]
    project.files.get.side_effect = lambda file_path, **_kwargs: _file_object(
        "blob-app", file_path, content=b"\x89PNG\r\n\x1a\n\x00\x00binary"
    )

    assert _poll(connector) == []


def test_poll_propagates_non_404_file_errors(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.commits.list.return_value = [
        _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    ]
    project.files.get.side_effect = GitlabGetError("500 boom", response_code=500)

    with pytest.raises(GitlabGetError):
        _poll(connector)


def test_poll_falls_back_to_full_walk_when_commit_listing_fails(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.commits.list.side_effect = GitlabError("gitlab is unhappy")

    docs = _poll(connector)

    assert sorted(doc.id for doc in docs) == ["blob-app", "blob-readme"]
    # The fallback is the pre-existing walk, so it must not stamp fetch time.
    assert all(doc.doc_updated_at is None for doc in docs)


def test_poll_falls_back_to_full_walk_on_a_wide_change_set(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.commits.list.return_value = [
        _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    ] * MAX_POLL_COMMITS

    assert sorted(doc.id for doc in _poll(connector)) == ["blob-app", "blob-readme"]


def test_poll_falls_back_to_full_walk_without_a_default_branch(
    connector: GitlabConnector, project: MagicMock
) -> None:
    project.default_branch = None

    docs = _poll(connector)

    assert sorted(doc.id for doc in docs) == ["blob-app", "blob-readme"]
    project.commits.list.assert_not_called()


def test_load_from_state_still_yields_every_file(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """Pruning enumerates ids with this path, so it must stay complete."""
    docs = _walk(connector)

    assert sorted(doc.id for doc in docs) == ["blob-app", "blob-readme"]
    project.commits.list.assert_not_called()


def test_full_walk_never_stamps_fetch_time(connector: GitlabConnector) -> None:
    """The fix: a fetch-time stamp disarms the pipeline's content hash gate."""
    docs = _walk(connector)

    assert docs
    assert all(doc.doc_updated_at is None for doc in docs)


def test_poll_queries_gitlab_with_the_window_and_paginates_diffs(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """Pin the API contract.

    `commit.diff` forwards kwargs to `http_list`, which paginates only on
    `get_all`. Without it a large commit returns one page and the poll silently
    drops changed paths.
    """
    commit = _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    project.commits.list.return_value = [commit]

    _poll(connector)

    commit.diff.assert_called_once_with(get_all=True)
    _, kwargs = project.commits.list.call_args
    assert kwargs["ref_name"] == DEFAULT_BRANCH
    assert kwargs["since"] == WINDOW_START.isoformat()
    assert kwargs["until"] == WINDOW_END.isoformat()
    assert kwargs["per_page"] == MAX_POLL_COMMITS


def test_poll_and_walk_agree_on_document_id(
    connector: GitlabConnector, project: MagicMock
) -> None:
    """Pruning deletes indexed ids the walk does not produce, so ids must match."""
    project.commits.list.return_value = [
        _commit([{"new_path": "src/app.py", "old_path": "src/app.py"}])
    ]
    polled = {doc.id for doc in _poll(connector)}

    project.commits.list.return_value = []
    walked = {doc.id for doc in _walk(connector)}

    assert polled <= walked
