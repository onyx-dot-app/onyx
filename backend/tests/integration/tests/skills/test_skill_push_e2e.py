"""End-to-end push tests: admin HTTP API → on-disk side effect.

These tests close the loop on the skill-push pipeline by going through
the real admin HTTP endpoints and asserting the resulting file changes
on the granted user's local sandbox workspace. They depend on the
integration deployment running with ``SANDBOX_BACKEND=local`` — when the
deployment is K8s-backed there's no host-filesystem to peek at, so the
tests skip with a precise reason.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from onyx.server.features.build.configs import ENABLE_CRAFT
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from tests.integration.common_utils.managers.skill import build_minimal_bundle
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.skills.conftest import provision_sandbox_for
from tests.integration.tests.skills.conftest import skills_dir_for_user

# Local-only marker. K8s deployments push to pods, not to the host
# filesystem; there's nothing observable from the test process there.
_requires_local_backend = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.LOCAL or not ENABLE_CRAFT,
    reason=(
        "Skill push on-disk verification requires SANDBOX_BACKEND=local "
        "and ENABLE_CRAFT=true; K8s pushes go to the sandbox pod, not "
        "the test host, and Craft-disabled deployments reject session creation."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_bundle_with_markdown(slug: str, body: str) -> bytes:
    """Bundle containing a ``SKILL.md`` whose body we can grep for later."""
    return build_minimal_bundle(
        slug,
        body=f"---\nname: {slug}\ndescription: e2e marker\n---\n\n{body}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_requires_local_backend
def test_admin_publish_lands_on_granted_users_disk(
    admin_user: DATestUser,
) -> None:
    """Admin POSTs a new public skill → file lands on the granted user's disk.

    The skill is created as ``is_public=True`` so every user (including
    the admin acting as a regular user here) is in the affected set.
    The pipeline:

      POST /admin/skills/custom (multipart bundle)
        → admin_skill_api creates the row + grants
        → push_skill_to_affected_sandboxes resolves affected users
        → LocalSandboxManager writes files under
          ``{SANDBOX_BASE_PATH}/{sandbox_id}/managed/skills/{slug}/SKILL.md``

    We verify the final byte-on-disk after the API call returns.
    """
    provision_sandbox_for(admin_user)

    slug = f"e2e-publish-{uuid4().hex[:8]}"
    marker = f"E2E-MARKER-{uuid4().hex}"
    bundle = _build_bundle_with_markdown(slug, marker)

    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=bundle,
        is_public=True,
    )
    assert skill.enabled is True

    skill_md = skills_dir_for_user(admin_user, slug) / "SKILL.md"
    assert skill_md.exists(), (
        f"SKILL.md did not land on disk at {skill_md} — push pipeline "
        f"may have skipped this sandbox or written to the wrong path."
    )
    contents = skill_md.read_text()
    assert marker in contents, (
        f"SKILL.md exists at {skill_md} but lacks the bundle's marker text; "
        f"likely a stale write from a previous skill of the same slug."
    )


@_requires_local_backend
def test_admin_disable_removes_from_disk(admin_user: DATestUser) -> None:
    """Admin disables (``enabled=False``) a previously-published skill →
    skill directory is removed from every previously-affected user's
    sandbox workspace on disk.
    """
    provision_sandbox_for(admin_user)

    slug = f"e2e-disable-{uuid4().hex[:8]}"
    bundle = _build_bundle_with_markdown(slug, "to-be-removed")
    skill = SkillManager.create_custom(
        admin_user,
        slug=slug,
        bundle_bytes=bundle,
        is_public=True,
    )

    skill_dir = skills_dir_for_user(admin_user, slug)
    assert skill_dir.exists(), (
        f"precondition: skill directory should exist after publish, got "
        f"missing {skill_dir}"
    )

    # Disable: the pipeline reruns the affected-users push, which rebuilds
    # the user's fileset *without* this skill. The LocalSandboxManager
    # swaps the ``managed/skills`` symlink to a fresh version dir that
    # excludes the disabled slug — so the slug directory is no longer
    # reachable via the live symlink.
    SkillManager.patch_custom(skill, admin_user, enabled=False)

    # After the swap, the slug subdir is unreachable through the live
    # symlink. ``exists()`` follows symlinks by default, so a missing
    # subdir under the swapped target reports False — which is what we
    # want.
    assert not skill_dir.exists(), (
        f"skill directory still reachable at {skill_dir} after disable — "
        f"push pipeline should have rebuilt the user's fileset without "
        f"the disabled slug."
    )
