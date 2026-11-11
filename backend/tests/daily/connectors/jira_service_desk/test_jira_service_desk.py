import unittest
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_desk.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira_service_desk.models import (
    JSMCustomerRequest,
    JSMServiceDesk,
)


class TestJiraServiceManagementConnector(unittest.TestCase):
    def setUp(self) -> None:
        self.connector = JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net",
            project_key="IT",
            batch_size=10,
        )
        self.connector.load_credentials(
            {
                "jira_base_url": "https://example.atlassian.net",
                "jira_user_email": "engineer@example.com",
                "jira_api_token": "dummy-token-secret-123",
            }
        )

    def test_load_credentials_validation(self) -> None:
        c = JiraServiceManagementConnector()
        with self.assertRaises(ConnectorValidationError):
            c.load_credentials({})

        with self.assertRaises(ConnectorValidationError):
            c.load_credentials({"jira_base_url": "https://example.atlassian.net"})

    def test_transform_to_document(self) -> None:
        req = JSMCustomerRequest(
            issueId="10001",
            issueKey="IT-101",
            requestTypeId="5",
            serviceDeskId="2",
            createdDate="2026-11-11T12:00:00Z",
            summary="Need VPN access setup",
            description="User requested Wireguard profile for remote work.",
            status="Waiting for support",
        )
        doc = self.connector._transform_to_document(req)

        self.assertEqual(doc.source, DocumentSource.JIRA_SERVICE_MANAGEMENT)
        self.assertIn("IT-101", doc.semantic_identifier)
        self.assertIn("VPN access", doc.semantic_identifier)
        self.assertEqual(doc.metadata["issue_key"], "IT-101")
        self.assertEqual(doc.metadata["status"], "Waiting for support")
        self.assertEqual(len(doc.sections), 1)
        self.assertIn("Wireguard profile", doc.sections[0].text)

    def test_load_from_state_batches(self) -> None:
        fake_desk = JSMServiceDesk(
            id="1",
            projectId="10000",
            projectKey="IT",
            projectName="IT Support",
        )
        fake_req = JSMCustomerRequest(
            issueId="1001",
            issueKey="IT-1",
            summary="Printer issue",
            description="Printer paper jam",
            status="Open",
            serviceDeskId="1",
        )

        assert self.connector.client is not None
        self.connector.client.get_service_desks = MagicMock(return_value=[fake_desk])
        self.connector.client.paginate_customer_requests = MagicMock(
            return_value=[fake_req]
        )

        batches = list(self.connector.load_from_state())
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)
        doc = batches[0][0]
        self.assertEqual(doc.metadata["issue_key"], "IT-1")

    def test_poll_source(self) -> None:
        fake_desk = JSMServiceDesk(
            id="1",
            projectId="10000",
            projectKey="IT",
            projectName="IT Support",
        )
        fake_req = JSMCustomerRequest(
            issueId="1002",
            issueKey="IT-2",
            summary="New Laptop",
            description="MacBook Pro request",
            status="In Progress",
            serviceDeskId="1",
        )

        assert self.connector.client is not None
        self.connector.client.get_service_desks = MagicMock(return_value=[fake_desk])
        self.connector.client.paginate_customer_requests = MagicMock(
            return_value=[fake_req]
        )

        batches = list(self.connector.poll_source(start=1700000000.0, end=1700050000.0))
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)
        doc = batches[0][0]
        self.assertEqual(doc.metadata["issue_key"], "IT-2")

    def test_retrieve_all_slim_docs(self) -> None:
        fake_desk = JSMServiceDesk(
            id="1",
            projectId="10000",
            projectKey="IT",
            projectName="IT Support",
        )
        fake_req = JSMCustomerRequest(
            issueId="1003",
            issueKey="IT-3",
            summary="Monitor Cable",
            status="Resolved",
            serviceDeskId="1",
        )

        assert self.connector.client is not None
        self.connector.client.get_service_desks = MagicMock(return_value=[fake_desk])
        self.connector.client.paginate_customer_requests = MagicMock(
            return_value=[fake_req]
        )

        slim_batches = list(self.connector.retrieve_all_slim_docs())
        self.assertEqual(len(slim_batches), 1)
        self.assertEqual(len(slim_batches[0]), 1)
        slim_doc = slim_batches[0][0]
        self.assertIn("IT-3", slim_doc.id)


if __name__ == "__main__":
    unittest.main()
