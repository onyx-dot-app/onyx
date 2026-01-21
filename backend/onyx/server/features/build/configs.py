import os
from enum import Enum


class SandboxBackend(str, Enum):
    """Backend mode for sandbox operations.

    LOCAL: Development mode - no snapshots, no automatic cleanup
    KUBERNETES: Production mode - full snapshots and cleanup
    """

    LOCAL = "local"
    KUBERNETES = "kubernetes"


# Sandbox backend mode (controls snapshot and cleanup behavior)
# "local" = no snapshots, no cleanup (for development)
# "kubernetes" = full snapshots and cleanup (for production)
SANDBOX_BACKEND = SandboxBackend(os.environ.get("SANDBOX_BACKEND", "local"))


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

# OpenCode disabled tools (comma-separated list)
# Available tools: bash, edit, write, read, grep, glob, list, lsp, patch,
#                  skill, todowrite, todoread, webfetch, question
# Example: "question,webfetch" to disable user questions and web fetching
_disabled_tools_str = os.environ.get("OPENCODE_DISABLED_TOOLS", "question")
OPENCODE_DISABLED_TOOLS: list[str] = [
    t.strip() for t in _disabled_tools_str.split(",") if t.strip()
]

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
