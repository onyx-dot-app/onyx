import os

API_SERVER_PROTOCOL = os.getenv("API_SERVER_PROTOCOL") or "http"
API_SERVER_HOST = os.getenv("API_SERVER_HOST") or "localhost"
API_SERVER_PORT = os.getenv("API_SERVER_PORT") or "8080"
API_SERVER_URL = f"{API_SERVER_PROTOCOL}://{API_SERVER_HOST}:{API_SERVER_PORT}"
MAX_DELAY = 45

GENERAL_HEADERS = {"Content-Type": "application/json"}

NUM_DOCS = 5
