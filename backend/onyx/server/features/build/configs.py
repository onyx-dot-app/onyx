import os
from enum import Enum
from pathlib import Path


class SandboxBackend(str, Enum):
    """Backend mode for sandbox operations.

    KUBERNETES: Production + dev (kind) - full snapshots and cleanup.
    DOCKER: Self-hosted docker-compose - api_server drives the Docker Engine.
    """

    KUBERNETES = "kubernetes"
    DOCKER = "docker"


def _parse_sandbox_backend(raw: str) -> SandboxBackend:
    """Parse SANDBOX_BACKEND with a friendly error on the retired ``local`` value.

    The local backend was removed in favour of the kubernetes (kind) dev flow
    documented in ``docs/dev/local-kubernetes.md``. We raise a deliberate
    startup error rather than the bare ``ValueError`` from the enum
    constructor so the operator gets pointed at the migration path.
    """
    if raw.lower() == "local":
        raise RuntimeError(
            "SANDBOX_BACKEND=local is no longer supported. The local sandbox "
            "backend has been removed; use the kind-based Kubernetes dev flow. "
            "See docs/dev/local-kubernetes.md (run `make craft-up`) and unset "
            "SANDBOX_BACKEND in your environment (it now defaults to "
            "'kubernetes')."
        )
    try:
        return SandboxBackend(raw)
    except ValueError as e:
        raise RuntimeError(
            f"SANDBOX_BACKEND={raw!r} is not a valid value. Allowed values: "
            f"{[b.value for b in SandboxBackend]!r}. See "
            "docs/dev/local-kubernetes.md for the recommended dev setup."
        ) from e


# Sandbox backend mode (controls snapshot and cleanup behavior)
# "kubernetes" = full snapshots and cleanup (production Helm/cloud + dev kind)
# "docker" = full snapshots and cleanup (self-hosted docker-compose)
SANDBOX_BACKEND = _parse_sandbox_backend(
    os.environ.get("SANDBOX_BACKEND", "kubernetes")
)

# Base directory path for persistent document storage (local filesystem)
# Example: /var/onyx/file-system or /app/file-system
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get(
    "PERSISTENT_DOCUMENT_STORAGE_PATH", "/app/file-system"
)

_THIS_FILE = Path(__file__)

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

# Per-pod resource requests/limits. Defaults match production sizing for
# real bun/npm/python workloads. CI overrides these in kind clusters where
# the runner only has 4 vCPU and we provision 4+ sandbox pods concurrently;
# k8s scheduler honors requests, so the production defaults would prevent
# all-but-one pod from being scheduled at the same time.
SANDBOX_POD_CPU_REQUEST = os.environ.get("SANDBOX_POD_CPU_REQUEST", "1000m")
SANDBOX_POD_MEMORY_REQUEST = os.environ.get("SANDBOX_POD_MEMORY_REQUEST", "2Gi")
SANDBOX_POD_CPU_LIMIT = os.environ.get("SANDBOX_POD_CPU_LIMIT", "2000m")
SANDBOX_POD_MEMORY_LIMIT = os.environ.get("SANDBOX_POD_MEMORY_LIMIT", "10Gi")

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
