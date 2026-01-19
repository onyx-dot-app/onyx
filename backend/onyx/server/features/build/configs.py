import os

# Persistent Document Storage Configuration
# When enabled, indexed documents are written to local filesystem with hierarchical structure
PERSISTENT_DOCUMENT_STORAGE_ENABLED = (
    os.environ.get("PERSISTENT_DOCUMENT_STORAGE_ENABLED", "").lower() == "true"
)

# Base directory path for persistent document storage (local filesystem)
# Example: /var/onyx/indexed-docs or /app/indexed-docs
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_PATH", ""
)

SANDBOX_BASE_PATH = os.environ.get("SANDBOX_BASE_PATH", "")
OUTPUTS_TEMPLATE_PATH = os.environ.get("OUTPUTS_TEMPLATE_PATH", "")
VENV_TEMPLATE_PATH = os.environ.get("VENV_TEMPLATE_PATH", "")

# URL for the build webapp proxy endpoint
BUILD_WEBAPP_URL = os.environ.get("BUILD_WEBAPP_URL", "")
