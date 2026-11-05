"""Settings for the Firecracker sandbox runtime (`SANDBOX_RUNTIME=firecracker`).

Nothing here is read unless the runtime is Firecracker.
"""

import os

from onyx.server.features.build.configs import SANDBOX_RUNTIME, SandboxRuntime

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
SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS = float(
    os.environ.get("SANDBOX_FC_AGENT_RPC_TIMEOUT_SECONDS", "10")
)
SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS = float(
    os.environ.get("SANDBOX_FC_AGENT_CREATE_TIMEOUT_SECONDS", "45")
)

# Placement samples this many nodes per round and tries them by free memory.
SANDBOX_FC_PLACEMENT_CANDIDATES = max(
    1, int(os.environ.get("SANDBOX_FC_PLACEMENT_CANDIDATES", "3"))
)
# The placement record expires unless the reconcile loop or a heartbeat
# refreshes it. Keep it well above the reconcile interval.
SANDBOX_FC_PLACEMENT_TTL_SECONDS = int(
    os.environ.get("SANDBOX_FC_PLACEMENT_TTL_SECONDS", "300")
)
SANDBOX_FC_RECONCILE_INTERVAL_SECONDS = int(
    os.environ.get("SANDBOX_FC_RECONCILE_INTERVAL_SECONDS", "15")
)
# P4: a VM can sleep after this long without a heartbeat.
SANDBOX_FC_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("SANDBOX_FC_IDLE_TIMEOUT_SECONDS", "1800")
)
# Spreads the scheduled-task runs of one beat tick, so that they do not all
# start VMs at the same moment.
SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS = float(
    os.environ.get("SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS", "30")
)
