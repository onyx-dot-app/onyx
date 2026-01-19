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

# Sandbox filesystem paths
SANDBOX_BASE_PATH = os.environ.get("SANDBOX_BASE_PATH", "/tmp/onyx-sandboxes")
OUTPUTS_TEMPLATE_PATH = os.environ.get("OUTPUTS_TEMPLATE_PATH", "/templates/outputs")
VENV_TEMPLATE_PATH = os.environ.get("VENV_TEMPLATE_PATH", "/templates/venv")

# Sandbox agent configuration
SANDBOX_AGENT_COMMAND = os.environ.get("SANDBOX_AGENT_COMMAND", "opencode").split()

# Sandbox lifecycle configuration
SANDBOX_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_IDLE_TIMEOUT_SECONDS", "900")
)
SANDBOX_MAX_CONCURRENT_PER_ORG = int(
    os.environ.get("SANDBOX_MAX_CONCURRENT_PER_ORG", "10")
)

# Sandbox snapshot storage
SANDBOX_SNAPSHOTS_BUCKET = os.environ.get(
    "SANDBOX_SNAPSHOTS_BUCKET", "sandbox-snapshots"
)

# Next.js preview server port range
SANDBOX_NEXTJS_PORT_START = int(os.environ.get("SANDBOX_NEXTJS_PORT_START", "3010"))
SANDBOX_NEXTJS_PORT_END = int(os.environ.get("SANDBOX_NEXTJS_PORT_END", "3100"))

# URL for the build webapp proxy endpoint
BUILD_WEBAPP_URL = os.environ.get("BUILD_WEBAPP_URL", "")
