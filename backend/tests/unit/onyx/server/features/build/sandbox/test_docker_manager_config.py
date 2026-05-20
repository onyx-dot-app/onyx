"""Unit tests for ``DockerSandboxManager`` config helpers.

These tests exercise the pure naming / label / container-kwargs logic
without touching Docker. The kwargs builder is the load-bearing piece for
the sandbox's security posture (cap-drop, no-new-privileges, non-root
user, no socket mount, env allowlist), so we lock it down here.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _sandbox_container_name,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _sandbox_volume_name,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _sanitize_relative_path,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _validate_strict_path,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    build_container_create_kwargs,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    build_sandbox_labels,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    ContainerCreateKwargs,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    LABEL_COMPONENT,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    LABEL_COMPONENT_VALUE,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    LABEL_SANDBOX_ID,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    LABEL_TENANT_ID,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    LABEL_USER_ID,
)

SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_ID = "tenant-abc"


def test_container_name_matches_k8s_pattern() -> None:
    """K8s uses ``sandbox-<id8>``; Docker must match so dashboards/queries don't drift."""
    name = _sandbox_container_name(SANDBOX_ID)
    assert name == "sandbox-12345678"
    assert re.match(r"^sandbox-[a-f0-9]{8}$", name)


def test_volume_name_is_per_sandbox_and_short() -> None:
    """Volume name includes the sandbox prefix so cleanup queries can target it."""
    vol = _sandbox_volume_name(SANDBOX_ID)
    assert vol.endswith("12345678")
    assert vol.startswith("onyx-craft-sandbox-")


def test_labels_include_required_fields() -> None:
    labels = build_sandbox_labels(SANDBOX_ID, TENANT_ID, USER_ID)
    assert labels[LABEL_COMPONENT] == LABEL_COMPONENT_VALUE
    assert labels[LABEL_SANDBOX_ID] == str(SANDBOX_ID)
    assert labels[LABEL_TENANT_ID] == TENANT_ID
    assert labels[LABEL_USER_ID] == str(USER_ID)
    assert labels["app.kubernetes.io/managed-by"] == "onyx"


def test_labels_omit_user_id_when_none() -> None:
    """Volumes are created during ``_ensure_sandbox_volume`` before user resolution."""
    labels = build_sandbox_labels(SANDBOX_ID, TENANT_ID, None)
    assert LABEL_USER_ID not in labels
    assert labels[LABEL_SANDBOX_ID] == str(SANDBOX_ID)


@pytest.fixture
def kwargs() -> ContainerCreateKwargs:
    return build_container_create_kwargs(
        sandbox_id=SANDBOX_ID,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        image="onyxdotapp/sandbox:test",
        onyx_pat="pat-redacted",
        api_server_url="http://api_server:8080",
        network="onyx_craft_sandbox",
        volume_name="onyx-craft-sandbox-12345678",
        memory_limit="2g",
        cpu_limit=1.0,
    )


def test_container_kwargs_has_required_security_options(
    kwargs: ContainerCreateKwargs,
) -> None:
    """The sandbox must not be privileged or escalate caps."""
    assert kwargs["user"] == "1000:1000"
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["privileged"] is False


def test_container_kwargs_does_not_mount_docker_socket(
    kwargs: ContainerCreateKwargs,
) -> None:
    """If this regresses, the sandbox can pwn the host. Hard fail."""
    for mount in kwargs["volumes"]:
        assert "docker.sock" not in mount, f"sandbox would mount {mount!r}"


def test_container_kwargs_env_allowlist_excludes_storage_credentials(
    kwargs: ContainerCreateKwargs,
) -> None:
    env = kwargs["environment"]
    # Required env
    assert env["ONYX_PAT"] == "pat-redacted"
    assert env["ONYX_SERVER_URL"] == "http://api_server:8080"
    # Forbidden env - any storage credential leaking into the sandbox would
    # let the agent read every snapshot/file in the deployment.
    forbidden = {
        "S3_AWS_ACCESS_KEY_ID",
        "S3_AWS_SECRET_ACCESS_KEY",
        "MINIO_ROOT_PASSWORD",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "ONYX_SANDBOX_PUSH_PRIVATE_KEY",
    }
    leaked = forbidden & set(env)
    assert not leaked, f"Storage credentials leaked into sandbox env: {leaked}"


def test_container_kwargs_resource_limits(kwargs: ContainerCreateKwargs) -> None:
    assert kwargs["mem_limit"] == "2g"
    # 1.0 CPU → 1_000_000_000 nano-cpus.
    assert kwargs["nano_cpus"] == 1_000_000_000


def test_container_kwargs_labels_and_volume(kwargs: ContainerCreateKwargs) -> None:
    assert kwargs["labels"][LABEL_SANDBOX_ID] == str(SANDBOX_ID)
    assert "onyx-craft-sandbox-12345678" in kwargs["volumes"]
    assert (
        kwargs["volumes"]["onyx-craft-sandbox-12345678"]["bind"]
        == "/workspace/sessions"
    )


def test_container_kwargs_uses_sandbox_network(kwargs: ContainerCreateKwargs) -> None:
    """Sandbox must join only the dedicated bridge, not compose's default."""
    assert kwargs["network"] == "onyx_craft_sandbox"


# ---------------------------------------------------------------------------
# Path validators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("attachments/a.txt", "attachments/a.txt"),
        ("/outputs/web", "outputs/web"),
        ("../../etc/passwd", "etc/passwd"),
        ("..", "."),
        ("", "."),
    ],
)
def test_sanitize_relative_path(raw: str, expected: str) -> None:
    assert _sanitize_relative_path(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "%2e%2e/x",
        "x\x00y",
        "a;rm -rf /",
        "a|cat",
        "a&b",
    ],
)
def test_validate_strict_path_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_strict_path(bad)


@pytest.mark.parametrize(
    "good",
    [
        "attachments/file.txt",
        "outputs/web/page.tsx",
        "a/b/c.txt",
    ],
)
def test_validate_strict_path_accepts(good: str) -> None:
    _validate_strict_path(good)


# ---------------------------------------------------------------------------
# Network / data isolation invariants
# ---------------------------------------------------------------------------


def test_container_kwargs_env_is_a_minimal_allowlist(
    kwargs: ContainerCreateKwargs,
) -> None:
    """Lock the env schema. Adding any new key needs an explicit test update.

    This is the single point where any future contributor could leak a
    bucket name, host, or credential into the sandbox by accident — so we
    pin the full key set.
    """
    env = kwargs["environment"]
    assert isinstance(env, dict)
    assert set(env.keys()) == {"ONYX_PAT", "ONYX_SERVER_URL"}


def test_container_kwargs_mounts_only_workspace_sessions(
    kwargs: ContainerCreateKwargs,
) -> None:
    """The only host-side resource exposed to the agent is its own workspace volume."""
    volumes = kwargs["volumes"]
    assert len(volumes) == 1
    only_volume = next(iter(volumes.values()))
    assert only_volume["bind"] == "/workspace/sessions"
    # No bind mounts that could leak host secrets.
    for source in volumes:
        assert not source.startswith("/"), (
            f"Bind mount detected: {source}; only named volumes are allowed"
        )


def test_container_kwargs_warns_on_internal_compose_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deployers that point SANDBOX_API_SERVER_URL at compose DNS get warned."""
    import logging

    with caplog.at_level(logging.WARNING):
        build_container_create_kwargs(
            sandbox_id=SANDBOX_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            image="onyxdotapp/sandbox:test",
            onyx_pat="pat",
            api_server_url="http://api_server:8080",  # compose-internal DNS
            network="onyx_craft_sandbox",
            volume_name="vol",
            memory_limit="2g",
            cpu_limit=1.0,
        )
    assert any(
        "looks like an internal compose hostname" in r.getMessage()
        for r in caplog.records
    )


def test_container_kwargs_no_warning_for_public_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A public URL is the expected configuration; no warning fired."""
    import logging

    with caplog.at_level(logging.WARNING):
        build_container_create_kwargs(
            sandbox_id=SANDBOX_ID,
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            image="onyxdotapp/sandbox:test",
            onyx_pat="pat",
            api_server_url="https://onyx.example.com",
            network="onyx_craft_sandbox",
            volume_name="vol",
            memory_limit="2g",
            cpu_limit=1.0,
        )
    assert not any(
        "looks like an internal compose hostname" in r.getMessage()
        for r in caplog.records
    )
