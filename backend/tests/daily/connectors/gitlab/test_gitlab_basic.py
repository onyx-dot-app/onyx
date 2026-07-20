import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.gitlab.connector import GitlabConnector
from onyx.connectors.gitlab.connector import GitlabConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.GITLAB_ACCESS_TOKEN)


@pytest.fixture
def gitlab_connector(
    test_secrets: dict[TestSecret, str],
) -> GitlabConnector:
    connector = GitlabConnector(
        project_owner="onyx2895818",
        project_name="onyx",
        include_mrs=True,
        include_issues=True,
        include_code_files=True,
    )
    gitlab_url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    gitlab_token = test_secrets[TestSecret.GITLAB_ACCESS_TOKEN]

    connector.load_credentials(
        {
            "gitlab_access_token": gitlab_token,
            "gitlab_url": gitlab_url,
        }
    )
    return connector


def test_gitlab_connector_basic(gitlab_connector: GitlabConnector) -> None:
    checkpoint = gitlab_connector.build_dummy_checkpoint()
    results: list[Document | ConnectorFailure] = []
    while checkpoint.has_more:
        wrapper = CheckpointOutputWrapper[GitlabConnectorCheckpoint]()
        output = gitlab_connector.load_from_checkpoint(
            start=0,
            end=time.time(),
            checkpoint=checkpoint,
        )
        for document, _, failure, _ in wrapper(output):
            if document:
                results.append(document)
            elif failure:
                results.append(failure)
        assert wrapper.next_checkpoint is not None
        checkpoint = wrapper.next_checkpoint

    failures = [result for result in results if isinstance(result, ConnectorFailure)]
    assert not failures
    docs = [result for result in results if isinstance(result, Document)]
    assert len(docs) == 82

    validated_mr = False
    validated_issue = False
    validated_code_file = False
    gitlab_base_url = os.environ.get("GITLAB_URL", "https://gitlab.com").split("//")[-1]
    project_path = f"{gitlab_connector.project_owner}/{gitlab_connector.project_name}"

    target_mr_id = f"https://{gitlab_base_url}/{project_path}/-/merge_requests/1"
    target_issue_id = f"https://{gitlab_base_url}/{project_path}/-/work_items/2"
    target_code_file_semantic_id = "README.md"

    for doc in docs:
        assert doc.source == DocumentSource.GITLAB
        assert doc.secondary_owners is None
        assert doc.from_ingestion_api is False
        assert doc.additional_info is None
        assert isinstance(doc.id, str)
        assert doc.metadata is not None
        assert "type" in doc.metadata
        doc_type = doc.metadata["type"]

        assert len(doc.sections) >= 1
        section = doc.sections[0]
        assert isinstance(section.link, str)
        assert gitlab_base_url in section.link
        assert isinstance(section.text, str)

        if doc.id == target_mr_id and doc_type == "MergeRequest":
            assert doc.metadata["state"] == "opened"
            assert doc.semantic_identifier == "Add awesome feature"
            assert section.text == "This MR implements the awesome feature"
            assert doc.primary_owners is not None
            assert len(doc.primary_owners) == 1
            assert doc.primary_owners[0].display_name
            assert doc.primary_owners[0].display_name != "****"
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
            assert doc.primary_owners[0].display_name
            assert doc.primary_owners[0].display_name != "****"
            assert doc.id == section.link
            validated_issue = True
        elif (
            doc.semantic_identifier == target_code_file_semantic_id
            and doc_type == "CodeFile"
        ):
            assert doc.id != section.link
            assert section.link.endswith("/README.md")
            assert "# onyx" in section.text
            validated_code_file = True

        elif doc_type == "MergeRequest" and not validated_mr:
            assert "state" in doc.metadata
            assert gitlab_base_url in doc.id
            assert doc.id == section.link
        elif doc_type == "ISSUE" and not validated_issue:
            assert "state" in doc.metadata
            assert gitlab_base_url in doc.id
            assert doc.id == section.link
        elif doc_type == "CodeFile" and not validated_code_file:
            assert doc.id != section.link

    assert validated_mr, (
        f"Failed to find and validate the specific MergeRequest ({target_mr_id})."
    )
    assert validated_issue, (
        f"Failed to find and validate the specific Issue ({target_issue_id})."
    )
    assert validated_code_file, (
        f"Failed to find and validate the specific CodeFile ({target_code_file_semantic_id})."
    )
