from typing import TypedDict
from unittest.mock import MagicMock, PropertyMock, call

import gitlab
import pytest
from gitlab.exceptions import GitlabGetError

from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.models import Document


class BranchOptions(TypedDict, total=False):
    branch: str | None


@pytest.fixture
def gitlab_client() -> MagicMock:
    client = MagicMock(spec=gitlab.Gitlab)
    client.url = "https://gitlab.example.com"
    client.projects = MagicMock()
    project = client.projects.get.return_value
    project.default_branch = "main"
    project.repository_tree.side_effect = [
        [{"id": "tree-id", "name": "docs", "path": "docs", "type": "tree"}],
        [
            {
                "id": "blob-id",
                "name": "guide.md",
                "path": "docs/guide.md",
                "type": "blob",
            }
        ],
    ]
    project.files.get.return_value.decode.return_value = b"# Guide"
    return client


@pytest.mark.parametrize(
    "branch_options,expected_branch",
    [
        ({}, "main"),
        ({"branch": None}, "main"),
        ({"branch": ""}, "main"),
        ({"branch": " \t\n "}, "main"),
        ({"branch": "develop"}, "develop"),
        ({"branch": "  develop\t"}, "develop"),
        ({"branch": "feature/docs"}, "feature/docs"),
    ],
)
def test_code_uses_resolved_branch(
    gitlab_client: MagicMock,
    branch_options: BranchOptions,
    expected_branch: str,
) -> None:
    connector = GitlabConnector(
        "owner",
        "repo",
        include_mrs=False,
        include_issues=False,
        include_code_files=True,
        **branch_options,
    )
    connector.gitlab_client = gitlab_client
    project = gitlab_client.projects.get.return_value
    default_branch = PropertyMock(return_value="main")
    type(project).default_branch = default_branch

    documents = [doc for batch in connector.load_from_state() for doc in batch]

    assert connector.branch == (None if expected_branch == "main" else expected_branch)
    gitlab_client.projects.get.assert_called_once_with("owner/repo")
    assert project.repository_tree.call_args_list == [
        call(path="", all=True, ref=expected_branch),
        call(path="docs", all=True, ref=expected_branch),
    ]
    project.files.get.assert_called_once_with(
        file_path="docs/guide.md", ref=expected_branch
    )
    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, Document)
    assert document.id == "blob-id"
    assert document.sections[0].text == "# Guide"
    assert document.sections[0].link == (
        f"https://gitlab.example.com/owner/repo/-/blob/{expected_branch}/docs/guide.md"
    )
    assert default_branch.call_count == (0 if connector.branch else 1)


def test_code_disabled_makes_no_file_requests(gitlab_client: MagicMock) -> None:
    connector = GitlabConnector(
        "owner",
        "repo",
        include_mrs=False,
        include_issues=False,
        include_code_files=False,
        branch="feature/docs",
    )
    connector.gitlab_client = gitlab_client

    assert list(connector.load_from_state()) == []

    project = gitlab_client.projects.get.return_value
    project.repository_tree.assert_not_called()
    project.files.get.assert_not_called()


@pytest.mark.parametrize("failure_at", ["tree", "file"])
def test_invalid_branch_error_propagates(
    gitlab_client: MagicMock, failure_at: str
) -> None:
    connector = GitlabConnector(
        "owner",
        "repo",
        include_mrs=False,
        include_issues=False,
        include_code_files=True,
        branch="missing",
    )
    connector.gitlab_client = gitlab_client
    project = gitlab_client.projects.get.return_value
    error = GitlabGetError("Branch not found", response_code=404)
    if failure_at == "tree":
        project.repository_tree.side_effect = error
    else:
        project.files.get.side_effect = error

    with pytest.raises(GitlabGetError) as exc_info:
        list(connector.load_from_state())

    assert exc_info.value is error
    assert all(
        request.kwargs["ref"] == "missing"
        for request in project.repository_tree.call_args_list
    )
    if failure_at == "tree":
        project.files.get.assert_not_called()
    else:
        project.files.get.assert_called_once_with(
            file_path="docs/guide.md", ref="missing"
        )
