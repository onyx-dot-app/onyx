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
# placement record. The stop needs session saves (harness sandboxes); without
# them NoCheckpointSupport keeps every VM.
SANDBOX_FC_IDLE_TIMEOUT_SECONDS = _fc_env_int(
    "SANDBOX_FC_IDLE_TIMEOUT_SECONDS", 900, minimum=1
)
# Spreads the scheduled-task runs of one beat tick, so that they do not all
# start VMs at the same moment.
SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS = _fc_env_float(
    "SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS", 30.0, minimum=0.0
)

# Source image tag of the harness sandbox root drive (for example
# "dev-build-craft-fc-adf9a87"). Each node names its template
# "<tag>-<key hash>"; placement takes that node's newest template of the tag.
# Harness sandboxes need it.
SANDBOX_FC_TEMPLATE = os.environ.get("SANDBOX_FC_TEMPLATE", "").strip()
