import unittest
from unittest.mock import MagicMock, patch
from onyx.connectors.jsm.connector import JiraServiceManagementConnector
from onyx.configs.constants import DocumentSource

class TestJSMConnector(unittest.TestCase):
    def setUp(self):
        self.connector = JiraServiceManagementConnector(
            jira_base_url="https://test.atlassian.net",
            project_key="HELP"
        )
        self.mock_client = MagicMock()
        self.connector._client = self.mock_client

    def test_iterate_requests(self):
        # Mock service desk ID lookup
        self.mock_client.get_service_desk_id.return_value = "1"
        
        # Mock request list
        self.mock_client.get_requests.return_value = {
            "values": [
                {
                    "issueKey": "HELP-1",
                    "summary": "Test Request",
                    "description": "This is a test",
                    "createdDate": {"iso8601": "2023-10-27T10:00:00.000Z"},
                    "currentStatus": {"status": "Open"},
                    "reporter": {"displayName": "John Doe"}
                }
            ],
            "isLastPage": True
        }
        
        # Mock comments
        self.mock_client.get_comments.return_value = {
            "values": [
                {"body": {"text": "A comment"}}
            ]
        }
        
        # Run sync
        batches = list(self.connector.load_from_state())
        
        # Verify results
        self.assertEqual(len(batches), 1)
        documents = batches[0]
        self.assertEqual(len(documents), 1)
        doc = documents[0]
        
        self.assertEqual(doc.id, "HELP-1")
        self.assertEqual(doc.source, DocumentSource.JIRA_SERVICE_MANAGEMENT)
        self.assertEqual(doc.semantic_identifier, "HELP-1: Test Request")
        self.assertIn("This is a test", doc.sections[0].text)
        self.assertIn("A comment", doc.sections[0].text)
        self.assertEqual(doc.metadata["status"], "Open")
        self.assertEqual(doc.metadata["reporter"], "John Doe")

if __name__ == "__main__":
    unittest.main()
