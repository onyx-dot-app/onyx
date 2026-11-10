"""Settings for the Firecracker sandbox runtime (`SANDBOX_RUNTIME=firecracker`).

Every value is read at import, on every runtime. A malformed number logs an
error and uses the default, so it cannot break imports on other runtimes.
"""

import os

from onyx.server.features.build.configs import SANDBOX_RUNTIME, SandboxRuntime
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _fc_env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.error("Ignoring %s=%r: not a number. Using %s.", name, raw, default)
        return default
    return value if minimum is None else max(minimum, value)


def _fc_env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.error("Ignoring %s=%r: not an integer. Using %d.", name, raw, default)
        return default
    return value if minimum is None else max(minimum, value)


FIRECRACKER_ENABLED = SANDBOX_RUNTIME is SandboxRuntime.FIRECRACKER

# mTLS to the host agent listener (D2). PEM files, mounted by the deployment.
SANDBOX_FC_AGENT_CLIENT_CERT_PATH = os.environ.get(
    "SANDBOX_FC_AGENT_CLIENT_CERT_PATH", ""
).strip()
SANDBOX_FC_AGENT_CLIENT_KEY_PATH = os.environ.get(
    "SANDBOX_FC_AGENT_CLIENT_KEY_PATH", ""
).strip()
# CA that signed the agents' server certificate.
SANDBOX_FC_AGENT_CA_PATH = os.environ.get("SANDBOX_FC_AGENT_CA_PATH", "").strip()
# Name to verify in the agent certificate. The api_server dials agent pod IPs,
# so set this to the certificate's DNS name. Empty = verify the dialed host.
SANDBOX_FC_AGENT_TLS_SERVER_NAME = os.environ.get(
    "SANDBOX_FC_AGENT_TLS_SERVER_NAME", ""
).strip()

# Deadline of one agent call. Create waits for a snapshot restore (the agent's
# own --start-timeout is 30 s).
SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS = _fc_env_float(
    "SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS", 10.0
)
SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS = _fc_env_float(
    "SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS", 45.0
)

# Create retries (same attempt and key) when the guest daemon did not take
# the key in time (GUEST_UNREACHABLE).
SANDBOX_FC_CREATE_GUEST_RETRIES = _fc_env_int(
    "SANDBOX_FC_CREATE_GUEST_RETRIES", 2, minimum=0
)

# Placement samples this many nodes per round and tries them by free memory.
SANDBOX_FC_PLACEMENT_CANDIDATES = _fc_env_int(
    "SANDBOX_FC_PLACEMENT_CANDIDATES", 3, minimum=1
)
# The placement record expires unless the reconcile loop or a heartbeat
# refreshes it. Keep it well above the reconcile interval.
SANDBOX_FC_PLACEMENT_TTL_SECONDS = _fc_env_int("SANDBOX_FC_PLACEMENT_TTL_SECONDS", 300)
SANDBOX_FC_RECONCILE_INTERVAL_SECONDS = _fc_env_int(
    "SANDBOX_FC_RECONCILE_INTERVAL_SECONDS", 15
)
# P4: a VM can sleep after this long without a heartbeat.
SANDBOX_FC_IDLE_TIMEOUT_SECONDS = _fc_env_int("SANDBOX_FC_IDLE_TIMEOUT_SECONDS", 1800)
# Spreads the scheduled-task runs of one beat tick, so that they do not all
# start VMs at the same moment.
SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS = _fc_env_float(
    "SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS", 30.0
)
