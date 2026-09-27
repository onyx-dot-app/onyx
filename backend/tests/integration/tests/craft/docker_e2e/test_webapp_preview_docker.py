"""Webapp preview against a real Next dev server on the docker backend.

Docker counterpart of ``k8s/test_webapp_preview.py``: drives the shared
``start-webapp.sh`` the way the agent's `webapp` tool does, then pins that the
resulting dev server serves the basePath route through the proxy. A
docker-only divergence from the shared start script (or a broken basePath
contract) fails here and nowhere else — the k8s suite only covers the
kubernetes manager's side.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from onyx.server.features.build.configs import SANDBOX_BACKEND, SandboxBackend
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.craft.docker_e2e.conftest import (
    ProvisionSandbox,
    remove_container,
    session_webapp_logs,
    start_session_webapp,
)
from tests.integration.tests.craft.webapp_preview import (
    proxy_get,
    wait_for_webapp_ready,
)

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.DOCKER,
    reason="Docker integration tests require SANDBOX_BACKEND=docker.",
)


@pytest.fixture
def webapp_user() -> DATestUser:
    return UserManager.create(name=f"craft_docker_webapp_{uuid4().hex[:8]}")


def test_preview_serves_at_base_path_and_reports_ready(
    webapp_user: DATestUser,
    provision_sandbox: ProvisionSandbox,
) -> None:
    """``ready`` flips true and the route users actually load returns 200."""
    sandbox = provision_sandbox(webapp_user, headless=False)
    try:
        session_id = str(sandbox.session_id)
        bootstrap_output = start_session_webapp(
            sandbox.container_name, sandbox.session_id
        )
        wait_for_webapp_ready(
            webapp_user,
            session_id,
            diagnostics=lambda: (
                f"--- start-webapp.sh ---\n{bootstrap_output}\n"
                + session_webapp_logs(sandbox.container_name, sandbox.session_id)
            ),
        )

        resp = proxy_get(webapp_user, session_id)
        assert resp.status_code == 200, resp.text[:500]
    finally:
        remove_container(sandbox.container_name)
