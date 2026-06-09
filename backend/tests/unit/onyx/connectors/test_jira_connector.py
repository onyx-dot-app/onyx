import unittest
import sys
from unittest.mock import patch, MagicMock

# Atalho inteligente para mockar o ambiente pesado do Onyx durante testes locais rápidos
try:
    from onyx.connectors.interfaces import BaseConnector
except Exception:
    class BaseConnector:
        pass

# Importa o seu conector
try:
    from onyx.connectors.jira_connector import JiraConnector
except ModuleNotFoundError:
    # Se o PYTHONPATH não estiver setado, importa localmente para o teste passar
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../../backend')))
    from onyx.connectors.jira_connector import JiraConnector

class TestJiraConnector(unittest.TestCase):
    @patch('onyx.connectors.jira_connector.requests.get')
    def test_get_tickets_success(self, mock_get):
        # Configurando o mock para retornar uma resposta de sucesso
        mock_get.return_value = MagicMock(status_code=200)
        mock_get.return_value.json.return_value = {
            'issues': [
                {
                    'id': '1',
                    'fields': {
                        'summary': 'Ticket 1',
                        'status': {'name': 'Open'}
                    }
                }
            ]
        }

        connector = JiraConnector('username', 'token', 'http://jira.url')
        tickets = connector.get_tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]['summary'], 'Ticket 1')
        self.assertEqual(tickets[0]['status'], 'Open')

    @patch('onyx.connectors.jira_connector.requests.get')
    def test_get_tickets_failure(self, mock_get):
        # Configurando o mock para retornar uma resposta de erro
        mock_get.return_value = MagicMock(status_code=404)

        connector = JiraConnector('username', 'token', 'http://jira.url')
        tickets = connector.get_tickets()
        self.assertEqual(tickets, [])

if __name__ == '__main__':
    unittest.main()