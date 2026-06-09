import unittest
import sys
from unittest.mock import patch, MagicMock

# SRE Mocking layer to bypass production database and cache dependencies during local unit testing
mock_module = MagicMock()
mock_module.exceptions.RedisError = Exception
sys.modules['redis'] = mock_module
sys.modules['redis.exceptions'] = mock_module.exceptions

from onyx.connectors.jira_connector import JiraConnector
from onyx.connectors.models import Document

class TestJiraConnector(unittest.TestCase):
    @patch('onyx.connectors.jira_connector.requests.get')
    def test_get_tickets_success(self, mock_get):
        # Configure mock to return paginated success response
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {
            'startAt': 0,
            'maxResults': 50,
            'total': 1,
            'issues': [
                {
                    'id': '10001',
                    'key': 'PROJ-1',
                    'fields': {
                        'summary': 'Test Ticket',
                        'status': {'name': 'Open'},
                        'description': 'This is a test'
                    }
                }
            ]
        }

        # Passing correct constructor parameters: username, token, url, project_key
        connector = JiraConnector('user@company.com', 'api_token', 'https://company.atlassian.net', 'PROJ')
        
        # Executes the generator and collects documents
        generator = connector.load_from_state()
        batches = list(generator)
        
        self.assertEqual(len(batches), 1)
        documents = batches[0]
        self.assertEqual(len(documents), 1)
        
        doc = documents[0]
        self.assertIsInstance(doc, Document)
        self.assertEqual(doc.id, "jsm_ticket_10001")
        self.assertEqual(doc.semantic_identifier, "PROJ-1")
        self.assertIn("Test Ticket", doc.sections[0].text)

if __name__ == '__main__':
    unittest.main()