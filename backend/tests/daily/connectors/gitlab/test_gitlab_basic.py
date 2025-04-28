import itertools
import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.gitlab.connector import GitlabConnector


@pytest.fixture
def gitlab_connector() -> GitlabConnector:
    connector = GitlabConnector(
        project_owner="onyx2895818",
        project_name="onyx",
        include_mrs=True,
        include_issues=True,
        include_code_files=True,  # Include code files in the test
    )
    # Ensure GITLAB_ACCESS_TOKEN and optionally GITLAB_URL are set in the environment
    gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    gitlab_token = os.environ.get("GITLAB_ACCESS_TOKEN")

    if not gitlab_token:
        pytest.skip("GITLAB_ACCESS_TOKEN environment variable not set.")

    connector.load_credentials(
        {
            "gitlab_access_token": gitlab_token,
            "gitlab_url": gitlab_url,
        }
    )
    return connector


def test_gitlab_connector_basic(gitlab_connector: GitlabConnector) -> None:
    doc_batches = gitlab_connector.load_from_state()
    docs = list(itertools.chain(*doc_batches))
    # Assert right number of docs - Adjust if necessary based on test repo state
    assert len(docs) == 79

    # Find one of each type to validate
    validated_mr = False
    validated_issue = False
    validated_code_file = False
    gitlab_base_url = os.environ.get("GITLAB_URL", "https://gitlab.com").split("//")[-1]
    project_path = f"{gitlab_connector.project_owner}/{gitlab_connector.project_name}"

    # --- Specific Document Details to Validate ---
    target_mr_id = f"https://{gitlab_base_url}/{project_path}/-/merge_requests/1"
    target_issue_id = f"https://{gitlab_base_url}/{project_path}/-/issues/2"
    target_code_file_semantic_id = "README.md"
    # ---

    for doc in docs:
        # Verify basic document properties (common to all types)
        assert doc.source == DocumentSource.GITLAB
        assert doc.secondary_owners is None
        assert doc.from_ingestion_api is False
        assert doc.additional_info is None
        assert isinstance(doc.id, str)
        assert doc.metadata is not None
        assert "type" in doc.metadata
        doc_type = doc.metadata["type"]

        # Verify sections (common structure)
        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.link, str)
        assert gitlab_base_url in section.link
        assert isinstance(section.text, str)

        # --- Type-specific and Content Validation ---
        if doc.id == target_mr_id and doc_type == "MergeRequest":
            assert doc.metadata["state"] == "opened"
            assert doc.semantic_identifier == "Add awesome feature"
            assert section.text == "This MR implements the awesome feature"
            assert doc.primary_owners is not None
            assert len(doc.primary_owners) == 1
            assert (
                doc.primary_owners[0].display_name == "Test"
            )  # Adjust if author changes
            assert doc.id == section.link
            validated_mr = True
        elif doc.id == target_issue_id and doc_type == "ISSUE":
            assert doc.metadata["state"] == "opened"
            assert doc.semantic_identifier == "Investigate performance issue"
            assert (
                section.text
                == "Investigate and resolve the performance degradation on endpoint X"
            )
            assert doc.primary_owners is not None
            assert len(doc.primary_owners) == 1
            assert (
                doc.primary_owners[0].display_name == "Test"
            )  # Adjust if author changes
            assert doc.id == section.link
            validated_issue = True
        elif (
            doc.semantic_identifier == target_code_file_semantic_id
            and doc_type == "CodeFile"
        ):
            # ID is a git hash (e.g., 'd177...'), Link is the blob URL
            assert doc.id != section.link
            assert section.link.endswith("/README.md")
            assert "# onyx" in section.text  # Check for a known part of the content
            # Code files might not have primary owners assigned this way
            # assert len(doc.primary_owners) == 0
            validated_code_file = True

        # Generic validation for *any* document of the type if specific one not found yet
        elif doc_type == "MergeRequest" and not validated_mr:
            assert "state" in doc.metadata
            assert gitlab_base_url in doc.id  # MR ID should be a URL
            assert doc.id == section.link  # Link and ID are the same URL
        elif doc_type == "ISSUE" and not validated_issue:
            assert "state" in doc.metadata
            assert gitlab_base_url in doc.id  # Issue ID should be a URL
            assert doc.id == section.link  # Link and ID are the same URL
        elif doc_type == "CodeFile" and not validated_code_file:
            assert doc.id != section.link  # ID is GID/hash, link is blob URL

        # Early exit optimization (optional)
        # if validated_mr and validated_issue and validated_code_file:
        #     break

    # Assert that we found and validated the specific documents
    assert (
        validated_mr
    ), f"Failed to find and validate the specific MergeRequest ({target_mr_id})."
    assert (
        validated_issue
    ), f"Failed to find and validate the specific Issue ({target_issue_id})."
    assert (
        validated_code_file
    ), f"Failed to find and validate the specific CodeFile ({target_code_file_semantic_id})."
