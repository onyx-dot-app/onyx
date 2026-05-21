import time
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from github import Github
from github.RateLimit import RateLimit
from github.Requester import Requester

from onyx.connectors.github.connector import _is_indexable_path
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
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
    ],
)
def test_is_indexable_path(path: str, size: int | None, expected: bool) -> None:
    assert _is_indexable_path(path, size) is expected


@pytest.fixture
def mock_github_client() -> MagicMock:
    mock = MagicMock(spec=Github)
    mock.get_repo = MagicMock()
    mock.get_rate_limit = MagicMock(return_value=MagicMock(spec=RateLimit))
    mock._requester = MagicMock(spec=Requester)
    return mock


def _tree_element(path: str, size: int, type_: str = "blob") -> MagicMock:
    el = MagicMock()
    el.path = path
    el.size = size
    el.type = type_
    return el


@pytest.fixture
def create_mock_repo() -> Callable[..., MagicMock]:
    def _create(
        files: dict[str, bytes],
        pushed_at: datetime | None = None,
        truncated: bool = False,
    ) -> MagicMock:
        mock_repo = MagicMock()
        mock_repo.name = "test-repo"
        mock_repo.id = 1
        mock_repo.full_name = "test-org/test-repo"
        mock_repo.html_url = "https://github.com/test-org/test-repo"
        mock_repo.default_branch = "main"
        mock_repo.pushed_at = pushed_at or datetime(2023, 1, 1)
        mock_repo.configure_mock(
            raw_headers={"status": "200 OK"},
            raw_data={"id": 1, "full_name": "test-org/test-repo"},
        )

        tree = MagicMock()
        tree.tree = [_tree_element(p, len(c)) for p, c in files.items()]
        tree.raw_data = {"truncated": truncated}
        mock_repo.get_git_tree = MagicMock(return_value=tree)

        def _get_contents(path: str, ref: str | None = None) -> MagicMock:
            del ref  # accepted as a kwarg by the connector, unused in the mock
            cf = MagicMock()
            cf.decoded_content = files[path]
            return cf

        mock_repo.get_contents = MagicMock(side_effect=_get_contents)
        return mock_repo

    return _create


def _build_connector(
    mock_github_client: MagicMock, include_files: bool = True
) -> GithubConnector:
    connector = GithubConnector(
        repo_owner="test-org",
        repositories="test-repo",
        include_prs=False,
        include_issues=False,
        include_files=include_files,
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
