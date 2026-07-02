import os
from enum import Enum


class SandboxBackend(str, Enum):
    KUBERNETES = "kubernetes"
    DOCKER = "docker"


SANDBOX_BACKEND = SandboxBackend.KUBERNETES
_env_sandbox_backend = os.environ.get("SANDBOX_BACKEND", "").strip()
if _env_sandbox_backend:
    try:
        SANDBOX_BACKEND = SandboxBackend(_env_sandbox_backend.lower())
    except ValueError:
        raise ValueError(
            f"Invalid SANDBOX_BACKEND={_env_sandbox_backend!r}. Valid values: "
            f"{', '.join(b.value for b in SandboxBackend)}. Unset it to use the "
            f"default, or align it with this release if you recently changed "
            f"image versions."
        )

_disabled_tools_str = os.environ.get("OPENCODE_DISABLED_TOOLS", "question")
OPENCODE_DISABLED_TOOLS: list[str] = [
    t.strip() for t in _disabled_tools_str.split(",") if t.strip()
]


SANDBOX_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_IDLE_TIMEOUT_SECONDS", "3600")
)
SANDBOX_MAX_CONCURRENT_PER_ORG = int(
    os.environ.get("SANDBOX_MAX_CONCURRENT_PER_ORG", "10")
)
SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS", "180")
)
SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS = int(
    os.environ.get("SANDBOX_IDLE_CLEANUP_INTERVAL_SECONDS", "60")
)

SANDBOX_NEXTJS_PORT_START = int(os.environ.get("SANDBOX_NEXTJS_PORT_START", "3010"))
SANDBOX_NEXTJS_PORT_END = int(os.environ.get("SANDBOX_NEXTJS_PORT_END", "3100"))

MAX_UPLOAD_FILE_SIZE_MB = int(os.environ.get("BUILD_MAX_UPLOAD_FILE_SIZE_MB", "50"))
MAX_UPLOAD_FILE_SIZE_BYTES = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
MAX_UPLOAD_FILES_PER_SESSION = int(
    os.environ.get("BUILD_MAX_UPLOAD_FILES_PER_SESSION", "20")
)
MAX_TOTAL_UPLOAD_SIZE_MB = int(os.environ.get("BUILD_MAX_TOTAL_UPLOAD_SIZE_MB", "200"))
MAX_TOTAL_UPLOAD_SIZE_BYTES = MAX_TOTAL_UPLOAD_SIZE_MB * 1024 * 1024
ATTACHMENTS_DIRECTORY = "attachments"

# ==============================================================================
# Kubernetes sandbox (SANDBOX_BACKEND=kubernetes)
# ==============================================================================

SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "onyx-sandboxes")

SANDBOX_CONTAINER_IMAGE = (
    os.environ.get("SANDBOX_CONTAINER_IMAGE", "").strip() or "onyxdotapp/sandbox:latest"
)

# Set to "Always" only in internal environments that deliberately pin a mutable
# tag. Non-dev deployments should use app-aligned immutable tags.
SANDBOX_IMAGE_PULL_POLICY = os.environ.get("SANDBOX_IMAGE_PULL_POLICY", "IfNotPresent")

SANDBOX_SERVICE_ACCOUNT_NAME = os.environ.get("SANDBOX_SERVICE_ACCOUNT_NAME", "sandbox")

ENABLE_CRAFT = os.environ.get("ENABLE_CRAFT", "false").lower() == "true"

# Gates the built-in `browser` skill. Defaults on to match the sandbox image's
# build-time ENABLE_BROWSER ARG (also on); a browserless sandbox build must set
# this false too, else the skill is advertised without its runtime.
ENABLE_BROWSER = os.environ.get("ENABLE_BROWSER", "true").lower() == "true"

SANDBOX_PUSH_PRIVATE_KEY = os.environ.get("ONYX_SANDBOX_PUSH_PRIVATE_KEY", "")


# Provider types Craft supports. The recommended models per type come from the
# shared recommended-models config (served via /build/recommended-models).
BUILD_MODE_ALLOWED_PROVIDER_TYPES = ["anthropic", "openai", "openrouter"]

# apiKey sentinel for a supported provider the org hasn't configured. We register
# every supported provider so a cross-provider override never hits "model not
# found"; an unconfigured one fails closed instead (proxy 403 / upstream 401).
BUILD_MODE_NOT_CONFIGURED_API_KEY = "onyx-provider-not-configured"

# Dev/debug-only: exposes an SSE endpoint that tails the sandbox pod's
# opencode-serve container logs. Never enable in prod — the logs include LLM I/O
# and tool invocations that may contain sensitive data. When false, the endpoint
# 404s so the surface is gone, not just hidden.
ENABLE_OPENCODE_DEBUGGING = (
    os.environ.get("ENABLE_OPENCODE_DEBUGGING", "false").lower() == "true"
)

# Must be set when SANDBOX_BACKEND=kubernetes (no default — varies per
# deployment).
SANDBOX_API_SERVER_URL = os.environ.get("SANDBOX_API_SERVER_URL", "")

# ==============================================================================
# Sandbox egress proxy
# ==============================================================================

# Required when SANDBOX_BACKEND=kubernetes.
SANDBOX_PROXY_HOST = os.environ.get("SANDBOX_PROXY_HOST", "")
SANDBOX_PROXY_PORT = int(os.environ.get("SANDBOX_PROXY_PORT", "8080"))

SANDBOX_PROXY_LISTEN_PORT = int(os.environ.get("SANDBOX_PROXY_LISTEN_PORT", "8080"))
# Env-tunable on Helm only; compose's healthcheck.test hardcodes 8081 (can't
# read container env), so a compose change here desyncs the probe.
SANDBOX_PROXY_HEALTHZ_PORT = int(os.environ.get("SANDBOX_PROXY_HEALTHZ_PORT", "8081"))

# The CA Secret lives here; the CA ConfigMap is projected into SANDBOX_NAMESPACE
# so sandboxes can mount it (K8s does not allow cross-namespace ConfigMap
# mounts).
SANDBOX_PROXY_NAMESPACE = os.environ.get("SANDBOX_PROXY_NAMESPACE", "onyx")

SANDBOX_PROXY_CA_SECRET = os.environ.get("SANDBOX_PROXY_CA_SECRET", "sandbox-proxy-ca")
SANDBOX_PROXY_CA_CONFIGMAP = os.environ.get(
    "SANDBOX_PROXY_CA_CONFIGMAP", "sandbox-proxy-ca-bundle"
)

# Proxy-side bind path for the CA volume. Hardcoded because the compose
# `volumes:` mount target is the source of truth; an env override would silently
# desync.
SANDBOX_PROXY_CA_VOLUME_PATH = "/var/lib/sandbox-proxy/ca"

# Docker named-volume for the proxy CA. Hardcoded for the same reason as above.
SANDBOX_PROXY_CA_VOLUME_NAME = "sandbox_proxy_ca"

# Non-empty sentinel for every proxy-injected credential (ONYX_PAT + each
# opencode apiKey); the proxy overwrites the real value on the wire. Sandboxes
# never see the raw values.
SANDBOX_PROXY_INJECTED_PLACEHOLDER = "replaced_by_egress_proxy"

# ==============================================================================
# Docker sandbox (SANDBOX_BACKEND=docker, self-hosted docker-compose)
# ==============================================================================

# Mounted into the api_server container; api_server uses this to drive sandbox
# container lifecycle.
SANDBOX_DOCKER_SOCKET = os.environ.get("SANDBOX_DOCKER_SOCKET", "/var/run/docker.sock")

# Sandbox containers join only this network and never compose's default network,
# isolating them from api_server, postgres, redis, etc.
SANDBOX_DOCKER_NETWORK = os.environ.get("SANDBOX_DOCKER_NETWORK", "onyx_craft_sandbox")

SANDBOX_DOCKER_VOLUME_PREFIX = os.environ.get(
    "SANDBOX_DOCKER_VOLUME_PREFIX", "onyx-craft-sandbox-"
)

# Defaults match the Kubernetes sandbox pod's *requests* (1 CPU / 2Gi), not its
# limits (2 CPU / 10Gi). Single-VM docker-compose deployments rarely have the
# headroom to over-commit each sandbox to 10Gi.
SANDBOX_DOCKER_MEMORY_LIMIT = os.environ.get("SANDBOX_DOCKER_MEMORY_LIMIT", "2g")
SANDBOX_DOCKER_CPU_LIMIT = float(os.environ.get("SANDBOX_DOCKER_CPU_LIMIT", "1.0"))

# ==============================================================================
# SSE / opencode-serve
# ==============================================================================

SSE_KEEPALIVE_INTERVAL = float(os.environ.get("SSE_KEEPALIVE_INTERVAL", "15.0"))

# Wall-clock budget for one user-message turn against opencode-serve.
SANDBOX_TURN_TIMEOUT_SECONDS = float(
    os.environ.get("SANDBOX_TURN_TIMEOUT_SECONDS", "900.0")
)

# Match against the EXPOSE directive in the sandbox Dockerfile.
OPENCODE_SERVE_PORT = int(os.environ.get("OPENCODE_SERVE_PORT", "4096"))

# Env var inside the sandbox container that holds the per-pod HTTP Basic
# password for opencode serve. Internal contract — api_server writes this name
# and opencode-serve reads it, so both ends must agree.
OPENCODE_SERVER_PASSWORD = "OPENCODE_SERVER_PASSWORD"

# Opencode's serve implementation hard-codes the username to "opencode" when
# only OPENCODE_SERVER_PASSWORD is set; any other value yields a 401 (verified
# against opencode 1.15.7).
OPENCODE_SERVER_USERNAME = "opencode"

OPENCODE_SERVE_CONNECT_TIMEOUT = float(
    os.environ.get("OPENCODE_SERVE_CONNECT_TIMEOUT", "5.0")
)
OPENCODE_SERVE_REQUEST_TIMEOUT = float(
    os.environ.get("OPENCODE_SERVE_REQUEST_TIMEOUT", "30.0")
)
# Idle timeout for /event SSE. The reader reconnects (with backoff) if the
# stream is silent for this long.
OPENCODE_SERVE_EVENT_READ_TIMEOUT = float(
    os.environ.get("OPENCODE_SERVE_EVENT_READ_TIMEOUT", "60.0")
)

# ==============================================================================
# Rate limiting
# ==============================================================================

# Messages per week. Free users always get 5 messages total (not configurable).
# Per-user overrides are managed via the PostHog feature flag
# "craft-has-usage-limits".
CRAFT_PAID_USER_RATE_LIMIT = int(os.environ.get("CRAFT_PAID_USER_RATE_LIMIT", "25"))

# ==============================================================================
# User Library (user-uploaded raw files: xlsx, pptx, docx, etc.)
# ==============================================================================

USER_LIBRARY_MAX_FILE_SIZE_MB = int(
    os.environ.get("USER_LIBRARY_MAX_FILE_SIZE_MB", "500")
)
USER_LIBRARY_MAX_FILE_SIZE_BYTES = USER_LIBRARY_MAX_FILE_SIZE_MB * 1024 * 1024

USER_LIBRARY_MAX_TOTAL_SIZE_GB = int(
    os.environ.get("USER_LIBRARY_MAX_TOTAL_SIZE_GB", "10")
)
USER_LIBRARY_MAX_TOTAL_SIZE_BYTES = USER_LIBRARY_MAX_TOTAL_SIZE_GB * 1024 * 1024 * 1024

USER_LIBRARY_MAX_FILES_PER_UPLOAD = int(
    os.environ.get("USER_LIBRARY_MAX_FILES_PER_UPLOAD", "100")
)

USER_LIBRARY_CONNECTOR_NAME = "User Library"
USER_LIBRARY_CREDENTIAL_NAME = "User Library Credential"
USER_LIBRARY_SOURCE_DIR = "user_library"
