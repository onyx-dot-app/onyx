"""End-to-end: admin enables Slack → user connects → user provisions a
sandbox → the Slack skill bundle lands in that sandbox.

This is the full external-app delivery contract, exercised over real
HTTP against a running Onyx deployment (no mocking):

  1. Admin creates + enables a Slack external app.
  2. User is offered it but is not yet authenticated.
  3. User populates their per-user credentials → authenticated.
  4. User creates a Craft build session, which provisions their sandbox
     and synchronously hydrates skills + external-app bundles into it.
  5. The Slack bundle (SKILL.md + the slack_api.py wrapper) is present
     in the sandbox under the reserved `_external_apps/<id>-slack/` dir.

The final on-disk assertion only makes sense for the LOCAL sandbox
backend (a Kubernetes pod's filesystem isn't reachable from the test
process); the test skips cleanly otherwise. It also skips if Onyx Craft
is disabled in the target environment (set `ENABLE_CRAFT=true`).
"""

import time
from pathlib import Path

import pytest
import requests

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.external_app import ExternalAppManager
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser

# Slack's real provider contract: the user must supply `access_token`
# (no org-supplied fields), so an empty org-credentials map means the
# user alone gates authentication.
_SLACK_AUTH_TEMPLATE = {"Authorization": "Bearer {access_token}"}
_SLACK_USER_CREDENTIALS = {"access_token": "USER_SLACK_TOKEN"}


def _create_build_session(user: DATestUser) -> dict:
    """POST /build/sessions — provisions the user's sandbox inline and
    returns the DetailedSessionResponse JSON. Skips the whole test if
    Onyx Craft is disabled in this environment."""
    resp = requests.post(
        f"{API_SERVER_URL}/build/sessions",
        json={"user_work_area": "engineering", "user_level": "ic"},
        headers=user.headers,
        cookies=user.cookies,
    )
    if resp.status_code == 403:
        pytest.skip(
            "Onyx Craft is disabled in this environment "
            "(set ENABLE_CRAFT=true to run this test)."
        )
    resp.raise_for_status()
    return resp.json()


def _slack_bundle_skill_md(sandbox_id: str, app_id: int) -> Path:
    """Where the Slack bundle's SKILL.md lands for the local backend.

    Mirrors `_merge_external_app_bundles` (dir = `<id>-<app_type>`) and
    the local manager's mount of `/workspace/managed/skills` →
    `<sandbox>/managed/skills`.
    """
    return (
        Path(SANDBOX_BASE_PATH)
        / sandbox_id
        / "managed"
        / "skills"
        / "_external_apps"
        / f"{app_id}-slack"
        / "SKILL.md"
    )


def test_admin_enable_user_connect_provisions_slack_bundle(
    reset: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001 — session create needs an LLM
) -> None:
    if SANDBOX_BACKEND != SandboxBackend.LOCAL:
        pytest.skip(
            "Sandbox filesystem verification requires the LOCAL backend "
            f"(SANDBOX_BACKEND={SANDBOX_BACKEND})."
        )

    # 1. Admin creates + enables the Slack app.
    app = ExternalAppManager.create(
        user_performing_action=admin_user,
        name="Slack",
        description="Read and post Slack messages from Onyx Craft.",
        upstream_url_patterns=[r"https://slack\.com/api/.*"],
        auth_template=dict(_SLACK_AUTH_TEMPLATE),
        organization_credentials={},
        enabled=True,
        app_type=ExternalAppType.SLACK,
    )

    # 2. User is offered it but is not yet authenticated.
    user_app = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=app.id
    )
    assert user_app.app_type == ExternalAppType.SLACK
    assert user_app.authenticated is False

    # 3. User populates their credentials → authenticated.
    ExternalAppManager.upsert_user_credentials(
        user_performing_action=basic_user,
        app_id=app.id,
        credentials=_SLACK_USER_CREDENTIALS,
    )
    user_app = ExternalAppManager.get_for_user(
        user_performing_action=basic_user, app_id=app.id
    )
    assert user_app.authenticated is True

    # 4. User creates a build session → sandbox provisioned + skills
    #    hydrated synchronously within the request.
    session = _create_build_session(basic_user)
    sandbox = session.get("sandbox")
    assert sandbox is not None, f"No sandbox in session response: {session}"
    sandbox_id = sandbox["id"]

    # 5. The Slack bundle is present in the sandbox. Push happens inline
    #    before the response, but the local manager swaps the skills dir
    #    via an atomic symlink rename — allow a brief settle window.
    skill_md = _slack_bundle_skill_md(sandbox_id, app.id)
    deadline = time.monotonic() + 15
    while not skill_md.exists() and time.monotonic() < deadline:
        time.sleep(0.5)

    assert skill_md.exists(), (
        f"Slack skill bundle not found in sandbox at {skill_md}. "
        "Expected external-app hydration to deliver it on session create."
    )
    content = skill_md.read_text()
    assert "name: slack" in content
    assert "slack_api.py" in content
    # The stdlib wrapper ships alongside SKILL.md.
    assert (skill_md.parent / "slack_api.py").is_file()
