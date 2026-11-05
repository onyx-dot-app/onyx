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
