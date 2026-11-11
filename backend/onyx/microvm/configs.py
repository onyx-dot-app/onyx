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
    "SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS", 10.0, minimum=1.0
)
SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS = _fc_env_float(
    "SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS", 45.0, minimum=1.0
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
# A VM that a node reports with no placement record and no reservation is an
# orphan once this long has passed since the api_server first saw it. The
# default is two reports at the agent's default --state-report-interval (20 s).
SANDBOX_FC_ORPHAN_GRACE_SECONDS = _fc_env_int(
    "SANDBOX_FC_ORPHAN_GRACE_SECONDS", 40, minimum=0
)
# A registered node whose last accepted state report is older than this is
# dead to placement: a wake places the next attempt on a live node. The
# default is nine reports at the agent's default --state-report-interval
# (20 s), above the agent's 2 min backoff after failed reports. A node that
# never reported counts as live while it is registered. 0 turns the check off.
SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS = _fc_env_int(
    "SANDBOX_FC_NODE_REPORT_TIMEOUT_SECONDS", 180, minimum=0
)
# Most orphan Stops per node report. The rest wait for the next report, so a
# report stays fast.
SANDBOX_FC_ORPHAN_STOPS_PER_REPORT = _fc_env_int(
    "SANDBOX_FC_ORPHAN_STOPS_PER_REPORT", 8, minimum=1
)
# P4: the idle evictor stops a VM after this long without activity in its
# placement record. The stop needs session saves: until then
# NoCheckpointSupport keeps every VM.
SANDBOX_FC_IDLE_TIMEOUT_SECONDS = _fc_env_int(
    "SANDBOX_FC_IDLE_TIMEOUT_SECONDS", 1800, minimum=1
)
# Spreads the scheduled-task runs of one beat tick, so that they do not all
# start VMs at the same moment.
SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS = _fc_env_float(
    "SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS", 30.0, minimum=0.0
)

# Harness sandboxes. The new agent harness gets Firecracker sandboxes only
# when this is on (and SANDBOX_RUNTIME=firecracker). Opencode sessions keep
# the pod sandbox manager either way.
SANDBOX_FC_HARNESS_ENABLED = FIRECRACKER_ENABLED and os.environ.get(
    "SANDBOX_FC_HARNESS_ENABLED", ""
).strip().lower() in ("1", "true", "yes")
# Node template version for harness sandbox VMs (TemplateInfo.version).
SANDBOX_FC_TEMPLATE = os.environ.get("SANDBOX_FC_TEMPLATE", "").strip()
# Deadline of one exec_command. Background servers need a long one; the
# guest daemon caps it at 24 h.
SANDBOX_FC_EXEC_DEADLINE_SECONDS = _fc_env_float(
    "SANDBOX_FC_EXEC_DEADLINE_SECONDS", 4 * 3600.0, minimum=1.0
)
# A turn mark expires after this long without a renewal (begin_turn).
SANDBOX_FC_TURN_LEASE_SECONDS = _fc_env_int(
    "SANDBOX_FC_TURN_LEASE_SECONDS", 900, minimum=1
)
# A parked approval keeps the sandbox busy for at most this long.
SANDBOX_FC_APPROVAL_PARK_SECONDS = _fc_env_int(
    "SANDBOX_FC_APPROVAL_PARK_SECONDS", 24 * 3600, minimum=1
)
# Largest session file that publish_artifact copies to the file store.
SANDBOX_FC_PUBLISH_MAX_BYTES = _fc_env_int(
    "SANDBOX_FC_PUBLISH_MAX_BYTES", 100 << 20, minimum=1
)
