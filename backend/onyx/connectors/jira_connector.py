import requests

# Tenta herdar da classe base real do Onyx. Se falhar por falta de dependências de produção (como o Redis), cria o fallback local.
try:
    from onyx.connectors.interfaces import BaseConnector
except Exception:
    class BaseConnector:
        pass

class JiraConnector(BaseConnector):
    def __init__(self, username, token, url):
        self.username = username
        self.token = token
        self.url = url
        self.authenticate()

    def authenticate(self):
        print(f"Autenticando {self.username} no Jira em {self.url}")

    def get_tickets(self):
        url = f"{self.url}/rest/api/2/search"
        headers = {
            "Authorization": f"Basic {self.token}",
            "Content-Type": "application/json"
        }
        query = {
            "jql": "project = YOUR_PROJECT_KEY",  # Substitua YOUR_PROJECT_KEY pelo seu projeto
            "fields": ["summary", "status"]
        }
        response = requests.get(url, headers=headers, params=query)
        if response.status_code == 200:
            mapped_tickets = self.map_tickets(response.json().get('issues', []))
            return mapped_tickets
        else:
            print(f"Erro ao buscar tickets: {response.status_code} - {response.text}")
            return []

    def map_tickets(self, tickets):
        mapped = []
        for ticket in tickets:
            mapped.append({
                "id": ticket["id"],
                "summary": ticket["fields"]["summary"],
                "status": ticket["fields"]["status"]["name"]
            })
        return mapped