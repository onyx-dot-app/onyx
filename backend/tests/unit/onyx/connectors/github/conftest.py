"""Shared doubles for the GitHub connector unit tests."""

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from github import Github
from github.RateLimit import RateLimit
from github.Requester import Requester


@pytest.fixture
def mock_github_client() -> MagicMock:
    """A PyGithub client mock with the accessors the connector touches."""
    mock = MagicMock(spec=Github)
    mock.get_repo = MagicMock()
    mock.get_organization = MagicMock()
    mock.get_user = MagicMock()
    mock.get_rate_limit = MagicMock(return_value=MagicMock(spec=RateLimit))
    mock._requester = MagicMock(spec=Requester)
    return mock


def _tree_element(path: str, size: int, type_: str = "blob") -> MagicMock:
    el = MagicMock()
    el.path = path
    el.size = size
    el.type = type_
    return el


def make_mock_repo(
    *,
    name: str = "test-repo",
    id: int = 1,
    owner: str = "test-org",
    default_branch: str = "main",
    pushed_at: datetime | None = None,
    files: dict[str, bytes] | None = None,
    truncated: bool = False,
) -> MagicMock:
    """A PyGithub Repository mock.

    Pass `files` to also wire `get_git_tree` / `get_contents` off that
    mapping; leave it None to keep them plain mocks.
    """
    full_name = f"{owner}/{name}"
    repo = MagicMock()
    repo.name = name
    repo.id = id
    repo.full_name = full_name
    repo.html_url = f"https://github.com/{full_name}"
    repo.default_branch = default_branch
    repo.pushed_at = pushed_at or datetime(2023, 1, 1)

    raw_data: dict[str, Any] = {
        "id": id,
        "name": name,
        "full_name": full_name,
        "private": False,
        "description": "Test repository",
    }
    repo.configure_mock(
        raw_headers={"status": "200 OK", "content-type": "application/json"},
        raw_data=raw_data,
    )

    repo.get_pulls = MagicMock()
    repo.get_issues = MagicMock()
    repo.get_contents = MagicMock()

    if files is not None:
        tree = MagicMock()
        tree.tree = [_tree_element(p, len(c)) for p, c in files.items()]
        tree.raw_data = {"truncated": truncated}
        repo.get_git_tree = MagicMock(return_value=tree)

        def _get_contents(path: str, ref: str | None = None) -> MagicMock:
            del ref  # accepted as a kwarg by the connector, unused in the mock
            cf = MagicMock()
            cf.decoded_content = files[path]
            return cf

        repo.get_contents = MagicMock(side_effect=_get_contents)

    return repo
