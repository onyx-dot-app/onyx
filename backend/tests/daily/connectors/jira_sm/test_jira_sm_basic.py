"""Daily integration test for the Jira Service Management connector.

Requires a JSM project with at least one ticket. Set the following
environment variables before running:

    JIRA_BASE_URL     – e.g. https://your-org.atlassian.net
    JIRA_USER_EMAIL   – Atlassian account email
    JIRA_API_TOKEN    – API token
    JIRA_SM_PROJECT   – JSM project key (e.g. SUP)
"""

import os

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import build_connector


@pytest.fixture(scope="module")
def jira_sm_connector():
    base_url = os.environ.get("JIRA_BASE_URL")
    email = os.environ.get("JIRA_USER_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    project = os.environ.get("JIRA_SM_PROJECT", "SUP")

    if not all([base_url, email, token]):
        pytest.skip("JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN not set")

    connector = build_connector(
        source=DocumentSource.JIRA_SM,
        connector_specific_config={"project_key": project},
    )
    connector.load_credentials(
        {
            "jira_base_url": base_url,
            "jira_user_email": email,
            "jira_api_token": token,
        }
    )
    return connector


def test_jira_sm_load(jira_sm_connector):
    """Load at least one document from the JSM project."""
    docs = []
    for batch in jira_sm_connector.load_from_state():
        if hasattr(batch, '__iter__') and not isinstance(batch, str):
            docs.extend(batch)
        if len(docs) >= 1:
            break

    assert len(docs) >= 1, "Expected at least one JSM ticket"
    doc = docs[0]
    assert doc.id.startswith("jira_sm_")
    assert doc.source_metadata["source_type"] == DocumentSource.JIRA_SM


def test_jira_sm_slim(jira_sm_connector):
    """Slim document generation returns valid IDs."""
    slim_docs = []
    for output in jira_sm_connector.generate_slim_documents():
        slim_docs.extend(output.slim_documents)
        if len(slim_docs) >= 1:
            break

    assert len(slim_docs) >= 1
    assert all(d.doc_id.startswith("jira_sm_") for d in slim_docs)
