"""Browser-use test in the Craft k8s integration lane.

The agent's `browser` command has to work inside the locked-down sandbox pod,
which is the intersection of four things that have each broken before: Chromium
launching with --no-sandbox under the pod's dropped caps/seccomp, reaching the
public internet through the MITM egress proxy, and trusting the proxy CA for
HTTPS. A clean snapshot of a real HTTPS page exercises all of them at once
against a real pod + the chart's sandbox proxy.
"""

from __future__ import annotations

import pytest
from kubernetes import client

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.tests.craft.k8s.k8s_fixtures import pod_exec
from tests.integration.tests.craft.k8s.k8s_fixtures import PoolSession

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


class TestBrowserUse:
    def test_browser_fetches_https_through_egress_proxy(
        self,
        k8s_client: client.CoreV1Api,
        pool_session: PoolSession,
    ) -> None:
        _sandbox_id, session_id, pod_name = pool_session

        # Run `browser` from the session workspace (its cwd is how the wrapper
        # resolves --session), exactly as the agent would.
        out = pod_exec(
            k8s_client,
            pod_name,
            SANDBOX_NAMESPACE,
            f"cd /workspace/sessions/{session_id} "
            "&& browser open https://example.com && browser snapshot -i",
        )

        assert "Example Domain" in out, out
        # Guard the specific MITM-cert failure mode that has regressed before.
        assert "ERR_CERT_AUTHORITY_INVALID" not in out, out
