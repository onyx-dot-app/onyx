from unittest.mock import MagicMock

from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.models import Document


def test_gitlab_fetch_deduplicate_blobs():
    # Mocking GitLab project and its branches
    mock_gitlab_client = MagicMock()
    mock_gitlab_client.url = "https://gitlab.com"
    mock_project = MagicMock()
    mock_gitlab_client.projects.get.return_value = mock_project
    mock_project.default_branch = "main"

    # We want to test that 'main' and 'dev' have the same file content
    mock_branch_main = MagicMock()
    mock_branch_main.name = "main"
    mock_branch_dev = MagicMock()
    mock_branch_dev.name = "dev"

    # Return branches in an order that would normally cause duplicates if not sorted/deduped
    mock_project.branches.list.return_value = [mock_branch_dev, mock_branch_main]

    # Mocking repository tree: same file content (blob_id_shared) on both branches
    def mock_repository_tree(*_args, **kwargs):
        _path = kwargs.get("path")
        _ref = kwargs.get("ref")
        _all = kwargs.get("all")
        return [{"path": "README.md", "type": "blob", "name": "README.md", "id": "blob_id_shared"}]

    mock_project.repository_tree.side_effect = mock_repository_tree

    # Mocking project.files.get
    mock_file_obj = MagicMock()
    mock_file_obj.decode.return_value.decode.return_value = "content"
    mock_project.files.get.return_value = mock_file_obj

    connector = GitlabConnector(
        project_owner="owner",
        project_name="repo",
        include_code_files=True,
        include_mrs=False,
        include_issues=False
    )
    connector.gitlab_client = mock_gitlab_client

    # Run fetch
    doc_batches = list(connector._fetch_from_gitlab())

    # Check results
    all_docs = []
    for batch in doc_batches:
        for item in batch:
            if isinstance(item, Document):
                all_docs.append(item)

    # Should only have 1 document because they were identical
    assert len(all_docs) == 1

    # The document should be from the 'main' branch because it's the default and prioritized
    doc = all_docs[0]
    assert doc.metadata["branch"] == "main"
    assert doc.id == "https://gitlab.com/owner/repo/-/blob/main/README.md"

def test_gitlab_fetch_different_blobs():
    # Mocking GitLab project and its branches
    mock_gitlab_client = MagicMock()
    mock_gitlab_client.url = "https://gitlab.com"
    mock_project = MagicMock()
    mock_gitlab_client.projects.get.return_value = mock_project
    mock_project.default_branch = "main"

    mock_branch_main = MagicMock()
    mock_branch_main.name = "main"
    mock_branch_dev = MagicMock()
    mock_branch_dev.name = "dev"

    mock_project.branches.list.return_value = [mock_branch_main, mock_branch_dev]

    # Mocking repository tree: different file content on main vs dev
    def mock_repository_tree(*_args, **kwargs):
        _path = kwargs.get("path")
        _ref = kwargs.get("ref")
        _all = kwargs.get("all")
        if _ref == "main":
            return [{"path": "README.md", "type": "blob", "name": "README.md", "id": "blob_id_main"}]
        else:
            return [{"path": "README.md", "type": "blob", "name": "README.md", "id": "blob_id_dev"}]

    mock_project.repository_tree.side_effect = mock_repository_tree

    # Mocking project.files.get
    mock_file_obj = MagicMock()
    mock_file_obj.decode.return_value.decode.return_value = "content"
    mock_project.files.get.return_value = mock_file_obj

    connector = GitlabConnector(
        project_owner="owner",
        project_name="repo",
        include_code_files=True,
        include_mrs=False,
        include_issues=False
    )
    connector.gitlab_client = mock_gitlab_client

    # Run fetch
    doc_batches = list(connector._fetch_from_gitlab())

    # Check results
    all_docs = []
    for batch in doc_batches:
        for item in batch:
            if isinstance(item, Document):
                all_docs.append(item)

    # Should have 2 documents because they were different
    assert len(all_docs) == 2

    # Verify both exist
    assert any(d.metadata["branch"] == "main" for d in all_docs)
    assert any(d.metadata["branch"] == "dev" for d in all_docs)
