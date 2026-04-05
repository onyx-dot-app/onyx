import unittest
from unittest.mock import MagicMock, patch
from onyx.connectors.jsm.connector import JsmConnector, JsmConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.configs.constants import DocumentSource

class TestJsmConnector(unittest.TestCase):
    def setUp(self):
        self.connector = JsmConnector(jira_base_url="https://test.atlassian.net")
        self.connector.load_credentials({"jira_api_token": "token", "jira_user_email": "user@test.com"})

    @patch("onyx.connectors.jsm.connector.requests.get")
    def test_load_from_checkpoint(self, mock_get):
        # Mock requests list response
        mock_requests_resp = MagicMock()
        mock_requests_resp.json.return_value = {
            "values": [
                {
                    "issueKey": "SD-1",
                    "serviceDeskId": "1",
                    "requestTypeId": "10",
                    "currentStatus": {"status": "Open"},
                    "requestFieldValues": [
                        {"label": "Summary", "value": "Test Summary"},
                        {"label": "Description", "value": "Test Description"},
                    ]
                }
            ],
            "isLastPage": True
        }
        mock_requests_resp.raise_for_status.return_value = None
        
        # Mock comments response
        mock_comments_resp = MagicMock()
        mock_comments_resp.json.return_value = {
            "values": [
                {"body": {"content": [{"type": "paragraph", "content": [{"type": "text", "text": "Test Comment"}]}]}}
            ],
            "isLastPage": True
        }
        mock_comments_resp.raise_for_status.return_value = None
        
        # side_effect to handle multiple calls
        mock_get.side_effect = [mock_requests_resp, mock_comments_resp]
        
        checkpoint = JsmConnectorCheckpoint(offset=0, has_more=True)
        
        # Use a helper to consume generator and get return value
        gen = self.connector.load_from_checkpoint(0, 0, checkpoint)
        docs = []
        new_checkpoint = None
        try:
            while True:
                docs.append(next(gen))
        except StopIteration as e:
            new_checkpoint = e.value
            
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertIsInstance(doc, Document)
        self.assertEqual(doc.title, "SD-1 Test Summary")
        self.assertIn("Test Description", doc.sections[0].text)
        self.assertIn("Test Comment", doc.sections[0].text)
        self.assertEqual(doc.source, DocumentSource.JIRA_SERVICE_MANAGEMENT)
        
        self.assertIsInstance(new_checkpoint, JsmConnectorCheckpoint)
        self.assertEqual(new_checkpoint.offset, 1)

if __name__ == "__main__":
    unittest.main()
