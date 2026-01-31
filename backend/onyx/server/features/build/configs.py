import json
import os
from enum import Enum
from pathlib import Path


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

# Base directory path for persistent document storage (local filesystem)
# Example: /var/onyx/file-system or /app/file-system
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_PATH", "/app/file-system"
)

# Demo Data Path
# Local: Source tree path (relative to this file)
# Kubernetes: Baked into container image at /workspace/demo_data
_THIS_FILE = Path(__file__)
DEMO_DATA_PATH = str(
    _THIS_FILE.parent / "sandbox" / "kubernetes" / "docker" / "demo_data"
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
    os.environ.get("SANDBOX_IDLE_TIMEOUT_SECONDS", "3600")
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

# File upload configuration
MAX_UPLOAD_FILE_SIZE_MB = int(os.environ.get("BUILD_MAX_UPLOAD_FILE_SIZE_MB", "50"))
MAX_UPLOAD_FILE_SIZE_BYTES = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
MAX_UPLOAD_FILES_PER_SESSION = int(
    os.environ.get("BUILD_MAX_UPLOAD_FILES_PER_SESSION", "20")
)
MAX_TOTAL_UPLOAD_SIZE_MB = int(os.environ.get("BUILD_MAX_TOTAL_UPLOAD_SIZE_MB", "200"))
MAX_TOTAL_UPLOAD_SIZE_BYTES = MAX_TOTAL_UPLOAD_SIZE_MB * 1024 * 1024
ATTACHMENTS_DIRECTORY = "attachments"

# ============================================================================
# Kubernetes Sandbox Configuration
# Only used when SANDBOX_BACKEND = "kubernetes"
# ============================================================================

# Namespace where sandbox pods are created
SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "onyx-sandboxes")

# Container image for sandbox pods
# Should include Next.js template and opencode CLI
SANDBOX_CONTAINER_IMAGE = os.environ.get(
    "SANDBOX_CONTAINER_IMAGE", "onyxdotapp/sandbox:v0.1.0"
)

# S3 bucket for sandbox file storage (snapshots, knowledge files, uploads)
# Path structure: s3://{bucket}/{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz
#                 s3://{bucket}/{tenant_id}/knowledge/{user_id}/
#                 s3://{bucket}/{tenant_id}/uploads/{session_id}/
SANDBOX_S3_BUCKET = os.environ.get("SANDBOX_S3_BUCKET", "onyx-sandbox-files")

# Service account for sandbox pods (NO IRSA - no AWS API access)
SANDBOX_SERVICE_ACCOUNT_NAME = os.environ.get(
    "SANDBOX_SERVICE_ACCOUNT_NAME", "sandbox-runner"
)

# Service account for init container (has IRSA for S3 access)
SANDBOX_FILE_SYNC_SERVICE_ACCOUNT = os.environ.get(
    "SANDBOX_FILE_SYNC_SERVICE_ACCOUNT", "sandbox-file-sync"
)

ENABLE_CRAFT = os.environ.get("ENABLE_CRAFT", "false").lower() == "true"

# ============================================================================
# Rate Limiting Configuration
# ============================================================================

# Base rate limit for paid/subscribed users (messages per week)
# Free users always get 5 messages total (not configurable)
CRAFT_PAID_USER_RATE_LIMIT = int(os.environ.get("CRAFT_PAID_USER_RATE_LIMIT", "25"))

# Per-user rate limit overrides (JSON map of email -> limit)
# Example: {"admin@example.com": 100, "power-user@example.com": 50}
# Users in this map get their specified limit instead of the default
_user_limit_overrides_str = os.environ.get("CRAFT_USER_RATE_LIMIT_OVERRIDES", "{}")
try:
    CRAFT_USER_RATE_LIMIT_OVERRIDES: dict[str, int] = json.loads(
        _user_limit_overrides_str
    )
except json.JSONDecodeError:
    CRAFT_USER_RATE_LIMIT_OVERRIDES = {}
