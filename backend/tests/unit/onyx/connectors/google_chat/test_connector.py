import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from onyx.connectors.google_chat.connector import GoogleChatConnector
from onyx.connectors.models import SlimDocument
from onyx.access.models import ExternalAccess

class TestGoogleChatConnector(unittest.TestCase):
    def setUp(self):
        self.connector = GoogleChatConnector(space_names=["Space 1"])
        self.connector._credentials_json = {"type": "service_account"}

    @patch("onyx.connectors.google_chat.connector._build_chat_service")
    def test_retrieve_all_slim_docs_perm_sync(self, mock_build_service):
        # Mock service and responses
        mock_service = MagicMock()
        mock_build_service.return_value = mock_service
        
        # Mock spaces().list().execute()
        mock_service.spaces.return_value.list.return_value.execute.return_value = {
            "spaces": [{"name": "spaces/1", "displayName": "Space 1"}]
        }
        
        # Mock spaces().members().list().execute()
        mock_service.spaces.return_value.members.return_value.list.return_value.execute.return_value = {
            "memberships": [
                {"member": {"type": "HUMAN", "email": "user1@example.com"}},
                {"member": {"type": "HUMAN", "email": "user2@example.com"}},
            ]
        }
        
        # Mock spaces().messages().list().execute()
        mock_service.spaces.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [
                {"name": "spaces/1/messages/m1", "text": "Hello", "createTime": "2023-01-01T12:00:00Z"},
            ]
        }

        # Run the method
        batches = list(self.connector.retrieve_all_slim_docs_perm_sync())
        
        # Assertions
        self.assertEqual(len(batches), 1)
        batch = batches[0]
        self.assertEqual(len(batch), 1)
        
        doc = batch[0]
        self.assertIsInstance(doc, SlimDocument)
        self.assertEqual(doc.id, "GOOGLE_CHAT_spaces/1/messages/m1")
        self.assertIsInstance(doc.external_access, ExternalAccess)
        self.assertIn("user1@example.com", doc.external_access.external_user_emails)
        self.assertIn("user2@example.com", doc.external_access.external_user_emails)

if __name__ == "__main__":
    unittest.main()
