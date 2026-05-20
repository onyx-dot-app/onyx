import os
from enum import Enum
from pathlib import Path


class SandboxBackend(str, Enum):
    """Backend mode for sandbox operations.

    LOCAL: Development mode - no snapshots, no automatic cleanup
    KUBERNETES: Production mode (Helm/cloud) - full snapshots and cleanup
    DOCKER: Self-hosted docker-compose - api_server drives the Docker Engine
    """

    LOCAL = "local"
    KUBERNETES = "kubernetes"
    DOCKER = "docker"


# Sandbox backend mode (controls snapshot and cleanup behavior)
# "local" = no snapshots, no cleanup (for development)
# "kubernetes" = full snapshots and cleanup (production Helm/cloud)
# "docker" = full snapshots and cleanup (self-hosted docker-compose)
SANDBOX_BACKEND = SandboxBackend(os.environ.get("SANDBOX_BACKEND", "local"))

# Base directory path for persistent document storage (local filesystem)
# Example: /var/onyx/file-system or /app/file-system
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_PATH", "/app/file-system"
)

_THIS_FILE = Path(__file__)

# Sandbox filesystem paths
# TODO(security): the sandbox base path holds user-supplied code; the `/tmp`
# default is fine for dev but production should override via env (or we should
# pick a non-world-writable default like `/var/lib/onyx-sandboxes`).
SANDBOX_BASE_PATH = os.environ.get("SANDBOX_BASE_PATH", "/tmp/onyx-sandboxes")  # noqa: S108
OUTPUTS_TEMPLATE_PATH = os.environ.get("OUTPUTS_TEMPLATE_PATH", "/templates/outputs")
VENV_TEMPLATE_PATH = os.environ.get("VENV_TEMPLATE_PATH", "/templates/venv")
# "copy" (default, safe for production where the agent may pip install) or
# "symlink" (CI-only: node_modules + venv become symlinks to the template,
# saving ~45s of per-session copytree).
SANDBOX_TEMPLATE_MODE = os.environ.get("SANDBOX_TEMPLATE_MODE", "copy").lower()
SKILLS_TEMPLATE_PATH = str(
    _THIS_FILE.parent / "sandbox" / "kubernetes" / "docker" / "skills"
)

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
# Should include Next.js template, opencode CLI, and agent skills
SANDBOX_CONTAINER_IMAGE = os.environ.get(
    "SANDBOX_CONTAINER_IMAGE", "onyxdotapp/sandbox:v0.1.44"
)

# S3 bucket for sandbox file storage (snapshots, knowledge files, uploads)
# Path structure: s3://{bucket}/{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz
#                 s3://{bucket}/{tenant_id}/knowledge/{user_id}/
#                 s3://{bucket}/{tenant_id}/uploads/{session_id}/
SANDBOX_S3_BUCKET = os.environ.get("SANDBOX_S3_BUCKET", "onyx-sandbox-files")

# Service account for sandbox pods (needs IRSA for S3 snapshot access)
SANDBOX_SERVICE_ACCOUNT_NAME = os.environ.get(
    "SANDBOX_SERVICE_ACCOUNT_NAME", "sandbox-file-sync"
)

ENABLE_CRAFT = os.environ.get("ENABLE_CRAFT", "false").lower() == "true"

# Internal URL the sandbox uses to reach the Onyx API server.
# Must be set when SANDBOX_BACKEND=kubernetes (no default — varies per deployment).
SANDBOX_API_SERVER_URL = os.environ.get("SANDBOX_API_SERVER_URL", "")

# ============================================================================
# Docker Sandbox Configuration
# Only used when SANDBOX_BACKEND = "docker" (self-hosted docker-compose)
# ============================================================================

# Docker socket path on the api_server host. Mounted into the api_server
# container; api_server uses this to drive sandbox container lifecycle.
SANDBOX_DOCKER_SOCKET = os.environ.get("SANDBOX_DOCKER_SOCKET", "/var/run/docker.sock")

# Bridge network for sandbox containers. Sandbox containers join only this
# network and never compose's default network, isolating them from
# api_server, postgres, redis, etc.
SANDBOX_DOCKER_NETWORK = os.environ.get("SANDBOX_DOCKER_NETWORK", "onyx_craft_sandbox")

# Prefix for the per-sandbox named volumes that hold ``/workspace/sessions``.
SANDBOX_DOCKER_VOLUME_PREFIX = os.environ.get(
    "SANDBOX_DOCKER_VOLUME_PREFIX", "onyx-craft-sandbox-"
)

# Container resource limits. Memory accepts docker-style suffixes (``2g``).
# Defaults match the Kubernetes sandbox pod's *requests* (1 CPU / 2Gi),
# not its limits (2 CPU / 10Gi). Single-VM docker-compose deployments rarely
# have the headroom to over-commit each sandbox to 10Gi.
SANDBOX_DOCKER_MEMORY_LIMIT = os.environ.get("SANDBOX_DOCKER_MEMORY_LIMIT", "2g")
SANDBOX_DOCKER_CPU_LIMIT = float(os.environ.get("SANDBOX_DOCKER_CPU_LIMIT", "1.0"))

# If true, install an iptables rule inside each sandbox at provision time to
# DROP traffic to 169.254.169.254 (EC2/GCE metadata service). The install
# script must enable this on cloud VMs; the host must also block IMDS in its
# Docker bridge rules. Application-level blocking is best-effort and is not a
# substitute for host configuration.
SANDBOX_DOCKER_BLOCK_IMDS = (
    os.environ.get("SANDBOX_DOCKER_BLOCK_IMDS", "false").lower() == "true"
)

# ============================================================================
# SSE Streaming Configuration
# ============================================================================

# SSE keepalive interval in seconds - send keepalive comment if no events
SSE_KEEPALIVE_INTERVAL = float(os.environ.get("SSE_KEEPALIVE_INTERVAL", "15.0"))

# ============================================================================
# ACP (Agent Communication Protocol) Configuration
# ============================================================================

# Timeout for ACP message processing in seconds
# This is the maximum time to wait for a complete response from the agent
ACP_MESSAGE_TIMEOUT = float(os.environ.get("ACP_MESSAGE_TIMEOUT", "900.0"))

# ============================================================================
# Rate Limiting Configuration
# ============================================================================

# Base rate limit for paid/subscribed users (messages per week)
# Free users always get 5 messages total (not configurable)
# Per-user overrides are managed via PostHog feature flag "craft-has-usage-limits"
CRAFT_PAID_USER_RATE_LIMIT = int(os.environ.get("CRAFT_PAID_USER_RATE_LIMIT", "25"))

# ============================================================================
# User Library Configuration
# For user-uploaded raw files (xlsx, pptx, docx, etc.) in Craft
# ============================================================================

# Maximum size per file in MB (default 500MB)
USER_LIBRARY_MAX_FILE_SIZE_MB = int(
    os.environ.get("USER_LIBRARY_MAX_FILE_SIZE_MB", "500")
)
USER_LIBRARY_MAX_FILE_SIZE_BYTES = USER_LIBRARY_MAX_FILE_SIZE_MB * 1024 * 1024

# Maximum total storage per user in GB (default 10GB)
USER_LIBRARY_MAX_TOTAL_SIZE_GB = int(
    os.environ.get("USER_LIBRARY_MAX_TOTAL_SIZE_GB", "10")
)
USER_LIBRARY_MAX_TOTAL_SIZE_BYTES = USER_LIBRARY_MAX_TOTAL_SIZE_GB * 1024 * 1024 * 1024

# Maximum files per single upload request (default 100)
USER_LIBRARY_MAX_FILES_PER_UPLOAD = int(
    os.environ.get("USER_LIBRARY_MAX_FILES_PER_UPLOAD", "100")
)

# String constants for User Library entities
USER_LIBRARY_CONNECTOR_NAME = "User Library"
USER_LIBRARY_CREDENTIAL_NAME = "User Library Credential"
USER_LIBRARY_SOURCE_DIR = "user_library"
