import os

ADMIN_USER_NAME = "admin_user"

API_SERVER_PROTOCOL = os.getenv("API_SERVER_PROTOCOL") or "http"
API_SERVER_HOST = os.getenv("API_SERVER_HOST") or "127.0.0.1"
API_SERVER_PORT = os.getenv("API_SERVER_PORT") or "8080"
API_SERVER_URL = f"{API_SERVER_PROTOCOL}://{API_SERVER_HOST}:{API_SERVER_PORT}"
MAX_DELAY = 120

GENERAL_HEADERS = {"Content-Type": "application/json"}

NUM_DOCS = 5

MOCK_CONNECTOR_SERVER_HOST = os.getenv("MOCK_CONNECTOR_SERVER_HOST") or "localhost"
MOCK_CONNECTOR_SERVER_PORT = os.getenv("MOCK_CONNECTOR_SERVER_PORT") or 8001
