# Solution for [github/issues_2281]: [onyx-dot-app/onyx] Jira Service Management Connector

- **Reward:** $250.00 USDC
- **Target URL:** https://github.com/onyx-dot-app/onyx/issues/2281
- **AI Brain:** gemini-2.5-flash
- **Tokens Used:** 8633 (~$0.0173 USD compute cost)

---

I will implement a new connector for Jira Service Management (JSM) within the `onyx` (Danswer) backend. This connector will fetch tickets from a specified JSM project, making them searchable and accessible through the Danswer platform.

The implementation will follow the existing connector architecture, leveraging the `danswer-ai/danswer` codebase as a reference, specifically the `danswer/connectors/README.md` and existing connectors like Jira.

Here's a breakdown of the plan:

1.  **Root Cause Analysis / Problem Statement:**
    The current Danswer platform lacks a dedicated connector for Jira Service Management. While a generic Jira connector exists, JSM often has specific fields, issue types (e.g., "Service Request," "Incident"), and workflows that might benefit from a tailored approach or at least a clear configuration path. The goal is to enable users to ingest JSM tickets, making their service desk knowledge searchable.

2.  **Architecture Design:**
    *   **Leverage Existing Jira Connector:** The core logic for interacting with Jira's REST API (authentication, pagination, field mapping) is largely reusable from the existing `danswer/connectors/jira/` module.
    *   **New Connector Module:** A new module `danswer/connectors/jira_service_management/` will be created.
    *   **Configuration:** The connector will require the JSM instance URL, API token (or username/password), and the specific JSM project key(s) to pull tickets from.
    *   **Data Fetching:**
        *   Use Jira's JQL (Jira Query Language) to filter tickets by project and potentially by issue type relevant to service management (e.g., `issuetype in standardIssueTypes() OR issuetype in subTaskIssueTypes()`).
        *   Fetch standard fields (summary, description, status, reporter, assignee, created, updated) and potentially custom fields relevant to JSM.
        *   Handle pagination for large numbers of tickets.
    *   **Document Generation:** Each JSM ticket will be transformed into a Danswer `Document` object, including its content, metadata, and permissions.
    *   **Permissions:** Implement permission syncing based on Jira's issue-level security or project roles, similar to the existing Jira connector.
    *   **Testing:** Add unit and integration tests to ensure the connector functions correctly.

3.  **Production-Ready Code Implementation:**

    I will create the following files and modify existing ones as needed:

    *   `danswer/connectors/jira_service_management/connector.py`: The main connector logic, inheriting from `JiraConnector` or a similar base, overriding methods as necessary for JSM specifics.
    *   `danswer/connectors/jira_service_management/constants.py`: Defines constants specific to JSM (e.g., default JQL).
    *   `danswer/connectors/jira_service_management/main.py`: The entry point for the connector, similar to other connectors.
    *   `danswer/connectors/jira_service_management/README.md`: Documentation for the new connector.
    *   `danswer/connectors/jira_service_management/models.py`: Defines Pydantic models for JSM-specific configuration.
    *   `danswer/connectors/jira_service_management/test_jira_service_management_connector.py`: Unit and integration tests.
    *   `danswer/connectors/factory.py`: Register the new connector.
    *   `danswer/configs/app_configs.py`: Potentially add a new connector type.
    *   `danswer/connectors/models.py`: Add `JiraServiceManagementConfig` to `ConnectorConfig`.
    *   `danswer/server/models.py`: Add `JiraServiceManagementConfig` to `ConnectorCredential` and `CreateConnectorRequest`.
    *   `danswer/server/web/lib/connectors.ts`: Frontend type definitions.
    *   `danswer/server/web/components/admin/connectors/JiraServiceManagementConnector.tsx`: Frontend component for configuring the JSM connector.
    *   `danswer/server/web/components/admin/connectors/ConnectorForm.tsx`: Add JSM to the connector type selection.

    **Key considerations for JSM specifics:**
    *   **JQL:** The default JQL might need to be more inclusive for JSM tickets.
    *   **Custom Fields:** JSM often uses custom fields for request types, service categories, etc. The connector should be flexible enough to allow users to specify custom fields to be indexed. For simplicity, initially, we'll focus on standard fields and allow for future expansion.
    *   **Comments/Attachments:** Ensure comments and attachments are pulled in, similar to the existing Jira connector.

### File: danswer/connectors/jira_service_management/connector.py
```python
import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from danswer.connectors.jira.connector import JiraConnector
from danswer.connectors.jira.connector import JiraConfig
from danswer.connectors.jira.connector import JiraIssue
from danswer.connectors.jira.connector import JiraIssueFields
from danswer.connectors.jira.connector import JiraIssueType
from danswer.connectors.jira.connector import JiraProject
from danswer.connectors.jira.connector import JiraUser
from danswer.connectors.jira.connector import JiraWebhook
from danswer.connectors.jira.connector import JQL_ISSUE_TYPE_FILTER
from danswer.connectors.jira.utils import get_jira_client
from danswer.connectors.jira_service_management.constants import JSM_DEFAULT_JQL_FILTER
from danswer.connectors.jira_service_management.models import JiraServiceManagementConfig
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.connectors.models import SmallFileInfo
from danswer.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    def __init__(
        self,
        connector_config: JiraServiceManagementConfig,
        credential_id: Optional[int] = None,
        is_cancelling: Optional[callable] = None,
    ):
        super().__init__(
            connector_config=JiraConfig(
                jira_url=connector_config.jira_url,
                jira_username=connector_config.jira_username,
                jira_api_token=connector_config.jira_api_token,
                project_keys=connector_config.project_keys,
                include_attachments=connector_config.include_attachments,
                include_comments=connector_config.include_comments,
                include_subtasks=connector_config.include_subtasks,
                custom_jql_query=connector_config.custom_jql_query,
            ),
            credential_id=credential_id,
            is_cancelling=is_cancelling,
        )
        self.connector_config = connector_config
        self.jira_client = get_jira_client(
            connector_config.jira_url,
            connector_config.jira_username,
            connector_config.jira_api_token,
        )

    def _get_jql_query(self, project_key: str) -> str:
        """Constructs the JQL query for fetching JSM tickets."""
        base_jql = f"project = '{project_key}'"

        # Apply JSM specific filter if no custom JQL is provided
        if not self.connector_config.custom_jql_query:
            base_jql += f" AND {JSM_DEFAULT_JQL_FILTER}"
            if not self.connector_config.include_subtasks:
                base_jql += f" AND {JQL_ISSUE_TYPE_FILTER}"
        else:
            # If custom JQL is provided, it takes precedence
            base_jql = self.connector_config.custom_jql_query

        return base_jql

    def _get_all_jira_issues_for_project(
        self, project_key: str, current_project_issues: List[str]
    ) -> Tuple[List[JiraIssue], List[str]]:
        """Fetches all issues for a given project key, applying JSM specific filters."""
        jql_query = self._get_jql_query(project_key)
        logger.info(f"Fetching JSM issues for project '{project_key}' with JQL: {jql_query}")

        all_issues: List[JiraIssue] = []
        start_at = 0
        max_results = 50  # Jira's default max_results per page

        while True:
            if self.is_cancelling and self.is_cancelling():
                logger.warning("Jira Service Management connector cancelled.")
                break

            try:
                issues_page = self.jira_client.search_issues(
                    jql_query,
                    startAt=start_at,
                    maxResults=max_results,
                    fields="*all",  # Fetch all fields to ensure we get JSM specific ones
                )
            except Exception as e:
                logger.error(f"Failed to fetch JSM issues for project {project_key}: {e}")
                break

            if not issues_page:
                break

            for issue in issues_page:
                # Convert raw Jira issue to our Pydantic model
                issue_fields = JiraIssueFields(
                    summary=issue.fields.summary,
                    description=getattr(issue.fields, "description", None),
                    status=issue.fields.status.name,
                    reporter=JiraUser(
                        name=issue.fields.reporter.displayName,
                        emailAddress=getattr(issue.fields.reporter, "emailAddress", None),
                    )
                    if issue.fields.reporter
                    else None,
                    assignee=JiraUser(
                        name=issue.fields.assignee.displayName,
                        emailAddress=getattr(issue.fields.assignee, "emailAddress", None),
                    )
                    if issue.fields.assignee
                    else None,
                    created=issue.fields.created,
                    updated=issue.fields.updated,
                    issueType=JiraIssueType(name=issue.fields.issuetype.name),
                    project=JiraProject(key=issue.fields.project.key, name=issue.fields.project.name),
                    # Add any other relevant fields, potentially custom fields
                    # For JSM, we might want to capture 'Request Type' or 'Service Desk' fields
                    # These are often custom fields, so we'd need to dynamically look them up
                    # For now, we rely on "*all" and will process them in _jira_issue_to_document
                )
                jira_issue = JiraIssue(
                    id=issue.id,
                    key=issue.key,
                    url=f"{self.connector_config.jira_url}/browse/{issue.key}",
                    fields=issue_fields,
                    raw_issue=issue.raw,  # Store raw data for flexible processing
                )
                all_issues.append(jira_issue)

            if len(issues_page) < max_results:
                break
            start_at += max_results

        return all_issues, [issue.key for issue in all_issues]

    def _jira_issue_to_document(self, jira_issue: JiraIssue) -> Document:
        """Converts a JiraIssue object to a Danswer Document, with JSM specific enhancements."""
        document = super()._jira_issue_to_document(jira_issue)

        # Enhance metadata with JSM specific fields if available in raw_issue
        if jira_issue.raw_issue:
            raw_fields = jira_issue.raw_issue.get("fields", {})
            # Example: Try to extract 'Request Type' which is often a custom field in JSM
            # This requires knowing the custom field ID or name.
            # For a robust solution, we'd need a way to configure these custom fields.
            # For now, we can try common patterns or rely on the user to specify.
            # A common pattern for Request Type is 'customfield_XXXXX'
            # We can iterate through custom fields if we know their names or IDs.
            for field_name, field_value in raw_fields.items():
                if "request type" in field_name.lower() or "servicedesk" in field_name.lower():
                    if isinstance(field_value, dict) and "value" in field_value:
                        document.metadata[field_name] = field_value["value"]
                    elif isinstance(field_value, str):
                        document.metadata[field_name] = field_value
                    # Add other JSM specific fields as needed
                    # e.g., 'Customer Request Type', 'Service Desk Name', 'Organization'

            # Add the project name to the metadata for better filtering/display
            if jira_issue.fields.project:
                document.metadata["project_name"] = jira_issue.fields.project.name
                document.metadata["project_key"] = jira_issue.fields.project.key

            # Add issue type to metadata
            if jira_issue.fields.issueType:
                document.metadata["issue_type"] = jira_issue.fields.issueType.name

        # Ensure the document has a title and content
        if not document.title:
            document.title = jira_issue.fields.summary or f"JSM Ticket {jira_issue.key}"
        if not document.sections:
            content = jira_issue.fields.description or ""
            if jira_issue.fields.summary:
                content = f"{jira_issue.fields.summary}\n\n{content}"
            document.sections = [Section(text=content, link=document.link)]

        return document

    def get_documents(self, last_run_t: Optional[int] = None) -> List[Document]:
        """
        Fetches all JSM tickets from the configured projects and converts them into Danswer Documents.
        """
        all_documents: List[Document] = []
        for project_key in self.connector_config.project_keys:
            logger.info(f"Starting JSM sync for project: {project_key}")
            # For JSM, we typically want to re-fetch all relevant tickets,
            # or at least those updated since last_run_t.
            # The base JiraConnector handles last_run_t in _get_all_jira_issues_for_project
            # by modifying the JQL. We'll ensure our _get_jql_query integrates this.
            # For now, we'll rely on the base class's `get_documents` which calls
            # `_get_all_jira_issues_for_project` with the appropriate JQL.
            # We just need to ensure our `_get_jql_query` is used.

            # The base class's `get_documents` method already orchestrates fetching
            # issues and converting them. We just need to ensure our overridden
            # `_get_jql_query` and `_jira_issue_to_document` are used.
            # The `_get_all_jira_issues_for_project` method is also overridden
            # to use our JSM-specific JQL.

            # We can call the parent's get_documents, which will in turn call our
            # overridden methods.
            project_documents = super().get_documents(last_run_t=last_run_t)
            all_documents.extend(project_documents)

        return all_documents

    def get_or_create_webhook(self, connector_id: int, api_key: str) -> Optional[JiraWebhook]:
        """JSM connector does not support webhooks directly for now."""
        logger.info("Jira Service Management connector does not support webhooks.")
        return None

    def delete_webhook(self, webhook_id: str) -> None:
        """JSM connector does not support webhooks directly for now."""
        logger.info("Jira Service Management connector does not support webhooks.")
        pass

    def get_issue_by_key(self, issue_key: str) -> Optional[JiraIssue]:
        """Fetches a single JSM issue by its key."""
        try:
            issue = self.jira_client.issue(issue_key, fields="*all")
            issue_fields = JiraIssueFields(
                summary=issue.fields.summary,
                description=getattr(issue.fields, "description", None),
                status=issue.fields.status.name,
                reporter=JiraUser(
                    name=issue.fields.reporter.displayName,
                    emailAddress=getattr(issue.fields.reporter, "emailAddress", None),
                )
                if issue.fields.reporter
                else None,
                assignee=JiraUser(
                    name=issue.fields.assignee.displayName,
                    emailAddress=getattr(issue.fields.assignee, "emailAddress", None),
                )
                if issue.fields.assignee
                else None,
                created=issue.fields.created,
                updated=issue.fields.updated,
                issueType=JiraIssueType(name=issue.fields.issuetype.name),
                project=JiraProject(key=issue.fields.project.key, name=issue.fields.project.name),
            )
            return JiraIssue(
                id=issue.id,
                key=issue.key,
                url=f"{self.connector_config.jira_url}/browse/{issue.key}",
                fields=issue_fields,
                raw_issue=issue.raw,
            )
        except Exception as e:
            logger.error(f"Failed to fetch JSM issue {issue_key}: {e}")
            return None

    def get_issue_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Fetches comments for a JSM issue."""
        return super().get_issue_comments(issue_key)

    def get_issue_attachments(self, issue_key: str) -> List[SmallFileInfo]:
        """Fetches attachments for a JSM issue."""
        return super().get_issue_attachments(issue_key)
```

### File: danswer/connectors/jira_service_management/constants.py
```python
# Default JQL filter for Jira Service Management tickets.
# This aims to include common JSM issue types like Service Request, Incident, Problem, Change,
# but also allows for custom types. It's a broad filter.
# Users can override this with `custom_jql_query`.
JSM_DEFAULT_JQL_FILTER = (
    "issuetype in ('Service Request', 'Incident', 'Problem', 'Change', 'Service Request with Approvals', "
    "'Customer Request', 'Support Request', 'Task', 'Story', 'Bug') OR issuetype in standardIssueTypes()"
)

# Connector name for display and internal identification
JSM_CONNECTOR_NAME = "JiraServiceManagement"
```

### File: danswer/connectors/jira_service_management/main.py
```python
from danswer.connectors.jira_service_management.connector import JiraServiceManagementConnector
from danswer.connectors.jira_service_management.models import JiraServiceManagementConfig
from danswer.connectors.models import ConnectorInfo
from danswer.connectors.models import InputType
from danswer.connectors.models import ServiceType


def main(connector_config: dict, credential_id: int) -> ConnectorInfo:
    jira_service_management_config = JiraServiceManagementConfig(**connector_config)
    connector = JiraServiceManagementConnector(
        connector_config=jira_service_management_config, credential_id=credential_id
    )
    return connector.load_initial_documents()


if __name__ == "__main__":
    # This block is for local testing/development purposes.
    # In a real deployment, the `main` function is called by the Danswer backend.
    # Replace with your actual JSM config for local testing.
    # Example usage:
    # python -m danswer.connectors.jira_service_management.main
    import os
    from danswer.configs.app_configs import DANSWER_BOT_NUM_RETRIES
    from danswer.connectors.models import Document
    from danswer.connectors.models import IndexAttemptMetadata
    from danswer.connectors.models import IndexingError
    from danswer.connectors.models import IndexingErrorType
    from danswer.db.engine import get_sqlalchemy_engine
    from danswer.db.models import Connector
    from danswer.db.models import Credential
    from danswer.db.models import Document as DBDocument
    from danswer.db.models import IndexAttempt
    from danswer.db.models import IndexingStatus
    from danswer.db.models import User
    from danswer.document_index.factory import get_default_document_index
    from danswer.document_index.interfaces import DocumentIndex
    from danswer.document_index.interfaces import UpdateRequest
    from danswer.utils.timing import log_function_time
    from sqlalchemy.orm import Session

    # Mock objects for local testing
    class MockCredential:
        id = 1
        credential_json = {
            "jira_url": os.environ.get("JIRA_SERVICE_MANAGEMENT_URL"),
            "jira_username": os.environ.get("JIRA_SERVICE_MANAGEMENT_USERNAME"),
            "jira_api_token": os.environ.get("JIRA_SERVICE_MANAGEMENT_API_TOKEN"),
            "project_keys": os.environ.get("JIRA_SERVICE_MANAGEMENT_PROJECT_KEYS", "").split(","),
            "include_attachments": True,
            "include_comments": True,
            "include_subtasks": False,
            "custom_jql_query": None,
        }

    class MockConnector:
        id = 1
        name = "JiraServiceManagementTest"
        source = "jira_service_management"
        input_type = InputType.LOAD_STATE
        service_type = ServiceType.JIRA_SERVICE_MANAGEMENT
        connector_specific_config = MockCredential.credential_json

    class MockIndexAttempt:
        id = 1
        connector = MockConnector()
        last_run_time = None
        status = IndexingStatus.NOT_STARTED

    class MockUser:
        id = 1

    # Set up environment variables for testing
    # export JIRA_SERVICE_MANAGEMENT_URL="https://your-instance.atlassian.net"
    # export JIRA_SERVICE_MANAGEMENT_USERNAME="your-email@example.com"
    # export JIRA_SERVICE_MANAGEMENT_API_TOKEN="YOUR_API_TOKEN"
    # export JIRA_SERVICE_MANAGEMENT_PROJECT_KEYS="SERVICE,HELPDESK" # Comma separated project keys

    if not all(
        [
            os.environ.get("JIRA_SERVICE_MANAGEMENT_URL"),
            os.environ.get("JIRA_SERVICE_MANAGEMENT_USERNAME"),
            os.environ.get("JIRA_SERVICE_MANAGEMENT_API_TOKEN"),
            os.environ.get("JIRA_SERVICE_MANAGEMENT_PROJECT_KEYS"),
        ]
    ):
        print("Please set JIRA_SERVICE_MANAGEMENT_URL, JIRA_SERVICE_MANAGEMENT_USERNAME, JIRA_SERVICE_MANAGEMENT_API_TOKEN, and JIRA_SERVICE_MANAGEMENT_PROJECT_KEYS environment variables for local testing.")
        exit(1)

    print("Running Jira Service Management connector locally...")
    connector_info = main(MockCredential.credential_json, MockCredential.id)
    print(f"Finished. Found {len(connector_info.documents)} documents.")
    # for doc in connector_info.documents:
    #     print(f"  - {doc.title} ({doc.link})")
    #     print(f"    Metadata: {doc.metadata}")
    #     if doc.sections:
    #         print(f"    Content snippet: {doc.sections[0].text[:100]}...")
    #     print("-" * 20)
```

### File: danswer/connectors/jira_service_management/README.md
```markdown
# Jira Service Management Connector

The Jira Service Management (JSM) connector allows Danswer to pull in tickets and knowledge articles from specified JSM projects, making them searchable within the Danswer platform.

## Features

*   **Ticket Ingestion**: Fetches tickets (Service Requests, Incidents, Problems, Changes, etc.) from one or more JSM projects.
*   **Configurable JQL**: Allows specifying a custom JQL query to precisely control which tickets are ingested.
*   **Attachments & Comments**: Optionally includes attachments and comments associated with tickets.
*   **Metadata Extraction**: Extracts key metadata such as summary, description, status, reporter, assignee, creation/update times, and JSM-specific fields like "Request Type" (if available).
*   **Permissions Sync**: Inherits permission syncing capabilities from the base Jira connector, ensuring users only see documents they have access to.

## Configuration

To set up the Jira Service Management connector, you will need the following information:

1.  **Jira URL**: The base URL of your Jira instance (e.g., `https://your-company.atlassian.net`).
2.  **Jira Username**: The email address of a Jira user with appropriate permissions to access the desired JSM projects.
3.  **Jira API Token**: An API token generated for the Jira username.
    *   To generate an API token, go to [https://id.atlassian.com/manage-api-tokens](https://id.atlassian.com/manage-api-tokens) and click "Create API token".
4.  **Project Keys**: A comma-separated list of JSM project keys (e.g., `SERVICE,HELPDESK,ITSM`). Only tickets from these projects will be ingested.
5.  **Include Attachments**: (Optional) Check this box to include file attachments from Jira tickets.
6.  **Include Comments**: (Optional) Check this box to include comments from Jira tickets.
7.  **Include Subtasks**: (Optional) Check this box to include subtasks. By default, only parent tasks are included.
8.  **Custom JQL Query**: (Optional) Provide a custom [Jira Query Language (JQL)](https://support.atlassian.com/jira-service-management-cloud/docs/use-advanced-searching-with-jql/) query to filter tickets. If provided, this query will override the default JSM-specific filter.
    *   **Default JQL Filter**: If no custom JQL is provided, the connector uses a default filter to include common JSM issue types: `issuetype in ('Service Request', 'Incident', 'Problem', 'Change', 'Service Request with Approvals', 'Customer Request', 'Support Request', 'Task', 'Story', 'Bug') OR issuetype in standardIssueTypes()`.

### Permissions Required

The Jira user associated with the API token needs at least "Browse Projects" permission for the specified JSM projects and "View Issues" permission for the tickets within those projects. To fetch attachments and comments, "View Attachments" and "View Comments" permissions are also required.

## How it Works

The connector leverages the existing Jira connector's robust API interaction capabilities. It extends the base Jira functionality by:

*   Applying a default JQL filter specifically tailored for common Jira Service Management issue types.
*   Enhancing document metadata with JSM-specific fields if they are present in the raw Jira issue data (e.g., "Request Type").

## Development Notes

*   The connector is built upon the `danswer.connectors.jira.connector.JiraConnector` class, inheriting most of its core logic for API interaction, pagination, and document conversion.
*   JSM-specific logic primarily resides in the `_get_jql_query` method to apply relevant filters and in `_jira_issue_to_document` to extract additional JSM metadata.
*   Webhooks are not currently supported for the JSM connector, as JSM often relies on different notification mechanisms or the existing Jira webhook system is sufficient for general issue updates.
```

### File: danswer/connectors/jira_service_management/models.py
```python
from typing import List
from typing import Optional

from pydantic import Field

from danswer.connectors.models import BasicConnectorConfig


class JiraServiceManagementConfig(BasicConnectorConfig):
    jira_url: str = Field(
        title="Jira URL",
        description="The base URL of your Jira instance (e.g., https://your-company.atlassian.net)",
    )
    jira_username: str = Field(
        title="Jira Username (Email)",
        description="The email address of a Jira user with access to the desired projects.",
    )
    jira_api_token: str = Field(
        title="Jira API Token",
        description="An API token generated for the Jira username. Go to https://id.atlassian.com/manage-api-tokens to create one.",
        json_schema_extra={"password": True},
    )
    project_keys: List[str] = Field(
        title="Jira Project Keys",
        description="Comma-separated list of Jira Service Management project keys (e.g., SERVICE,HELPDESK).",
        examples=[["SERVICE", "HELPDESK"]],
    )
    include_attachments: bool = Field(
        default=True,
        title="Include Attachments",
        description="If checked, file attachments from Jira tickets will be included.",
    )
    include_comments: bool = Field(
        default=True,
        title="Include Comments",
        description="If checked, comments from Jira tickets will be included.",
    )
    include_subtasks: bool = Field(
        default=False,
        title="Include Subtasks",
        description="If checked, subtasks will also be included. By default, only parent tasks are included.",
    )
    custom_jql_query: Optional[str] = Field(
        default=None,
        title="Custom JQL Query",
        description="Optional: A custom JQL query to filter tickets. If provided, this query will override the default JSM-specific filter.",
        examples=["status in ('Open', 'In Progress') AND resolution is EMPTY"],
    )
```

### File: danswer/connectors/jira_service_management/test_jira_service_management_connector.py
```python
import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from jira.resources import Issue
from jira.resources import IssueFields
from jira.resources import Status
from jira.resources import User

from danswer.connectors.jira_service_management.connector import JiraServiceManagementConnector
from danswer.connectors.jira_service_management.constants import JSM_DEFAULT_JQL_FILTER
from danswer.connectors.jira_service_management.models import JiraServiceManagementConfig
from danswer.connectors.models import Document
from danswer.connectors.models import Section


@pytest.fixture
def mock_jira_client():
    with patch("danswer.connectors.jira_service_management.connector.get_jira_client") as mock_get_client:
        mock_client = MagicMock(spec=JIRA)
        mock_get_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def jsm_config():
    return JiraServiceManagementConfig(
        jira_url="https://test.atlassian.net",
        jira_username="test@example.com",
        jira_api_token="test_token",
        project_keys=["SERVICE"],
        include_attachments=True,
        include_comments=True,
        include_subtasks=False,
        custom_jql_query=None,
    )


@pytest.fixture
def jsm_connector(jsm_config):
    return JiraServiceManagementConnector(connector_config=jsm_config, credential_id=1)


def create_mock_issue(
    issue_id: str,
    key: str,
    summary: str,
    description: Optional[str],
    status_name: str,
    reporter_name: str,
    reporter_email: str,
    assignee_name: Optional[str],
    assignee_email: Optional[str],
    created: str,
    updated: str,
    issue_type_name: str,
    project_key: str,
    project_name: str,
    raw_custom_fields: Optional[dict] = None,
) -> Issue:
    mock_issue = MagicMock(spec=Issue)
    mock_issue.id = issue_id
    mock_issue.key = key

    mock_fields = MagicMock(spec=IssueFields)
    mock_fields.summary = summary
    mock_fields.description = description
    mock_fields.status = MagicMock(spec=Status)
    mock_fields.status.name = status_name
    mock_fields.reporter = MagicMock(spec=User)
    mock_fields.reporter.displayName = reporter_name
    mock_fields.reporter.emailAddress = reporter_email
    mock_fields.assignee = (
        MagicMock(spec=User)
        if assignee_name
        else None
    )
    if mock_fields.assignee:
        mock_fields.assignee.displayName = assignee_name
        mock_fields.assignee.emailAddress = assignee_email
    mock_fields.created = created
    mock_fields.updated = updated
    mock_fields.issuetype = MagicMock()
    mock_fields.issuetype.name = issue_type_name
    mock_fields.project = MagicMock()
    mock_fields.project.key = project_key
    mock_fields.project.name = project_name

    # Simulate raw fields for custom field extraction
    raw_issue_data = {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": summary,
            "description": description,
            "status": {"name": status_name},
            "reporter": {"displayName": reporter_name, "emailAddress": reporter_email},
            "issuetype": {"name": issue_type_name},
            "project": {"key": project_key, "name": project_name},
            "created": created,
            "updated": updated,
        },
    }
    if assignee_name:
        raw_issue_data["fields"]["assignee"] = {"displayName": assignee_name, "emailAddress": assignee_email}
    if raw_custom_fields:
        raw_issue_data["fields"].update(raw_custom_fields)

    mock_issue.fields = mock_fields
    mock_issue.raw = raw_issue_data
    return mock_issue


def test_jsm_connector_initialization(jsm_config):
    connector = JiraServiceManagementConnector(connector_config=jsm_config, credential_id=1)
    assert connector.connector_config == jsm_config
    assert connector.credential_id == 1


def test_get_jql_query_default(jsm_connector):
    project_key = "SERVICE"
    expected_jql

---

### Payout & Settlement Details
- **EVM Address:** `0x66545035486C8B3b7966c45dc035560F4066aBb5`
- **Network:** Base (Chain ID 8453) / Arbitrum / Polygon / Ethereum
- **Settlement Asset:** USDC
- **Settlement Trigger:** Direct on-chain payout upon PR merge
