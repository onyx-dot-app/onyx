import time
from typing import cast

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

# JSM shares Jira's REST API and credential scheme, so the existing Jira test
# secrets exercise this connector end-to-end against a real service desk
# project. See the PR description for the exact JSM project the maintainers
# can set up with these credentials to re-run this test.
pytestmark = pytest.mark.secrets(
    TestSecret.JIRA_USER_EMAIL,
    TestSecret.JIRA_API_TOKEN,
    TestSecret.JIRA_API_TOKEN_SCOPED,
)

JSK_BASE_URL = "https://danswerai.atlassian.net"
# The 'AS' project on the test instance is a Jira Software project. The JSM
# connector accepts any project key; for the daily test we point it at the same
# known-good project the Jira connector tests use, which proves the subclass
# machinery (auth, JQL, pagination, document processing) works end-to-end.
JSK_PROJECT_KEY = "AS"


def _make_connector(
    test_secrets: dict[TestSecret, str],
    project_key: str = JSK_PROJECT_KEY,
    scoped_token: bool = False,
) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=JSK_BASE_URL,
        project_key=project_key,
        comment_email_blacklist=[],
        scoped_token=scoped_token,
    )
    connector.load_credentials(
        {
            "jira_user_email": test_secrets[TestSecret.JIRA_USER_EMAIL],
            "jira_api_token": (
                test_secrets[TestSecret.JIRA_API_TOKEN_SCOPED]
                if scoped_token
                else test_secrets[TestSecret.JIRA_API_TOKEN]
            ),
        }
    )
    return connector


@pytest.fixture
def jsm_connector(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets)


@pytest.fixture
def jsm_connector_scoped(
    test_secrets: dict[TestSecret, str],
) -> JiraServiceManagementConnector:
    return _make_connector(test_secrets, scoped_token=True)


def test_jsm_connector_settings_validate(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Settings validation must succeed against the reachable instance."""
    jsm_connector.validate_connector_settings()


def test_jsm_connector_settings_validation_bad_project(
    test_secrets: dict[TestSecret, str],
) -> None:
    """An unknown project key must fail validation loudly."""
    from onyx.connectors.exceptions import (
        ConnectorValidationError,
        CredentialExpiredError,
        InsufficientPermissionsError,
        UnexpectedValidationError,
    )

    connector = _make_connector(test_secrets, project_key="NO_SUCH_PROJECT_XYZ")
    with pytest.raises(
        (
            ConnectorValidationError,
            CredentialExpiredError,
            InsufficientPermissionsError,
            UnexpectedValidationError,
        )
    ):
        connector.validate_connector_settings()


def test_jsm_connector_basic(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """The JSM connector indexes the project's issues like the Jira connector.

    The subclass must produce the same documents the Jira connector does for
    the same project: same ids, same sections, same metadata. That equality is
    the contract — JSM tickets are Jira issues.
    """
    result = load_all_from_connector(
        connector=jsm_connector,
        start=0,
        end=time.time(),
    )
    docs = result.documents
    assert len(docs) == 2

    story: Document | None = None
    epic: Document | None = None
    for doc in docs:
        if doc.metadata["issuetype"] == "Story":
            story = doc
        elif doc.metadata["issuetype"] == "Epic":
            epic = doc

    assert story is not None
    assert epic is not None

    # Same identity/shape guarantees as the Jira connector test.
    assert story.id == "https://danswerai.atlassian.net/browse/AS-3"
    assert story.semantic_identifier == "AS-3: Magic Answers"
    assert story.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert story.metadata["project"] == "AS"
    assert story.metadata["key"] == "AS-3"
    assert len(story.sections) == 1
    assert story.sections[0].link == "https://danswerai.atlassian.net/browse/AS-3"

    assert epic.id == "https://danswerai.atlassian.net/browse/AS-4"
    assert epic.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_connector_basic_scoped(
    jsm_connector_scoped: JiraServiceManagementConnector,
) -> None:
    """Scoped tokens must work identically (same Atlassian credential scheme)."""
    jsm_connector_scoped.validate_connector_settings()
    result = load_all_from_connector(
        connector=jsm_connector_scoped,
        start=0,
        end=time.time(),
    )
    assert len(result.documents) == 2


def test_jsm_connector_slim_docs(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    """Slim retrieval (pruning path) must list the same document ids."""
    from onyx.connectors.models import HierarchyNode, SlimDocument

    slim_batches = list(
        jsm_connector.retrieve_all_slim_docs(
            start=0.0,
        )
    )
    ids: set[str] = set()
    for batch in slim_batches:
        for item in batch:
            if isinstance(item, HierarchyNode):
                continue
            slim_doc = cast(SlimDocument, item)
            ids.add(slim_doc.id)
    assert "https://danswerai.atlassian.net/browse/AS-3" in ids
    assert "https://danswerai.atlassian.net/browse/AS-4" in ids
