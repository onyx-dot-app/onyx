"""Unit tests for ``DockerSandboxManager`` config helpers.

These tests exercise the pure naming / label / container-kwargs logic without
touching Docker. The kwargs builder is the load-bearing piece for the sandbox's
security posture (cap-drop, no-new-privileges, non-root user, no socket mount,
env allowlist), so we lock it down here.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from uuid import UUID

import pytest

import onyx.server.features.build.sandbox.docker.docker_sandbox_manager as dsm
from onyx.server.features.build.configs import SANDBOX_PROXY_INJECTED_PLACEHOLDER
from onyx.server.features.build.sandbox.docker.dev_mode_serve import (
    OPENCODE_SERVE_CONTAINER_PORT,
)
from onyx.server.features.build.sandbox.docker.dev_mode_serve import (
    OPENCODE_SERVE_HOST_BIND_IP,
)
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
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_TMP_PATH,
)
from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    SANDBOX_TMPFS_OPTIONS,
)
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY
from onyx.server.features.build.sandbox.labels import LABEL_K8S_MANAGED_BY_ONYX

SANDBOX_ID = UUID("12345678-1234-1234-1234-1234567890ab")
USER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_ID = "tenant-abc"


def _bare_manager_with_image(image: str) -> tuple[dsm.DockerSandboxManager, MagicMock]:
    mgr: dsm.DockerSandboxManager = object.__new__(dsm.DockerSandboxManager)
    docker = MagicMock()
    mgr._docker = docker  # type: ignore[attr-defined]
    mgr._image = image  # type: ignore[attr-defined]
    mgr._image_checked = False  # type: ignore[attr-defined]
    mgr._image_check_lock = threading.Lock()  # type: ignore[attr-defined]
    return mgr, docker


def test_container_name_matches_k8s_pattern() -> None:
    """
    K8s uses ``sandbox-<id8>``; Docker must match so dashboards/queries don't
    drift.
    """
    name = _sandbox_container_name(SANDBOX_ID)
    assert name == "sandbox-12345678"
    assert re.match(r"^sandbox-[a-f0-9]{8}$", name)


def test_volume_name_is_per_sandbox_and_short() -> None:
    """
    Volume name includes the sandbox prefix so cleanup queries can target it.
    """
    vol = _sandbox_volume_name(SANDBOX_ID)
    assert vol.endswith("12345678")
    assert vol.startswith("onyx-craft-sandbox-")


def test_labels_include_required_fields() -> None:
    labels = build_sandbox_labels(SANDBOX_ID, TENANT_ID, USER_ID)
    assert labels[LABEL_COMPONENT] == LABEL_COMPONENT_VALUE
    assert labels[LABEL_SANDBOX_ID] == str(SANDBOX_ID)
    assert labels[LABEL_TENANT_ID] == TENANT_ID
    assert labels[LABEL_USER_ID] == str(USER_ID)
    assert labels[LABEL_K8S_MANAGED_BY] == LABEL_K8S_MANAGED_BY_ONYX


def test_labels_omit_user_id_when_none() -> None:
    """
    Volumes are created during ``_ensure_sandbox_volume`` before user
    resolution.
    """
    labels = build_sandbox_labels(SANDBOX_ID, TENANT_ID, None)
    assert LABEL_USER_ID not in labels
    assert labels[LABEL_SANDBOX_ID] == str(SANDBOX_ID)


def test_immutable_sandbox_image_uses_cached_image_when_present() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:v4.1.2")

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.get.assert_called_once_with("onyxdotapp/sandbox:v4.1.2")
    docker.images.pull.assert_not_called()


def test_immutable_sandbox_image_pulls_when_missing() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:v4.1.2")
    docker.images.get.side_effect = dsm.NotFound("missing")

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.pull.assert_called_once_with("onyxdotapp/sandbox:v4.1.2")


def test_mutable_sandbox_image_refreshes_once() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:latest")

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]
    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.pull.assert_called_once_with("onyxdotapp/sandbox:latest")
    docker.images.get.assert_not_called()


def test_sandbox_image_refresh_is_thread_safe() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:latest")
    pull_started = threading.Event()
    finish_pull = threading.Event()

    def pull_image(_image: str) -> None:
        pull_started.set()
        assert finish_pull.wait(timeout=1)

    docker.images.pull.side_effect = pull_image

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(mgr._ensure_sandbox_image)  # type: ignore[attr-defined]
        assert pull_started.wait(timeout=1)
        second = executor.submit(mgr._ensure_sandbox_image)  # type: ignore[attr-defined]
        finish_pull.set()
        first.result(timeout=1)
        second.result(timeout=1)

    docker.images.pull.assert_called_once_with("onyxdotapp/sandbox:latest")


def test_implicit_latest_sandbox_image_refreshes() -> None:
    image = "onyxdotapp/sandbox"
    mgr, docker = _bare_manager_with_image(image)

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.pull.assert_called_once_with(image)
    docker.images.get.assert_not_called()


def test_mutable_sandbox_image_uses_cache_once_if_refresh_fails() -> None:
    # Avoid retrying the registry on every sandbox spinup. A process restart
    # gets another chance to refresh the moving tag.
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:edge")
    docker.images.pull.side_effect = dsm.APIError("registry unavailable")

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]
    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.pull.assert_called_once_with("onyxdotapp/sandbox:edge")
    docker.images.get.assert_called_once_with("onyxdotapp/sandbox:edge")


def test_mutable_sandbox_image_raises_if_refresh_fails_without_cache() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:beta")
    docker.images.pull.side_effect = dsm.APIError("registry unavailable")
    docker.images.get.side_effect = dsm.NotFound("missing")

    with pytest.raises(RuntimeError, match="Failed to pull sandbox image"):
        mgr._ensure_sandbox_image()  # type: ignore[attr-defined]


def test_local_dev_sandbox_image_uses_cached_image_when_present() -> None:
    mgr, docker = _bare_manager_with_image("onyxdotapp/sandbox:dev")

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.get.assert_called_once_with("onyxdotapp/sandbox:dev")
    docker.images.pull.assert_not_called()


def test_registry_port_untagged_image_refreshes_as_implicit_latest() -> None:
    image = "localhost:5001/onyx-sandbox"
    mgr, docker = _bare_manager_with_image(image)

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.pull.assert_called_once_with(image)
    docker.images.get.assert_not_called()


def test_digest_sandbox_image_uses_cached_image_when_present() -> None:
    image = "onyxdotapp/sandbox@sha256:abc123"
    mgr, docker = _bare_manager_with_image(image)

    mgr._ensure_sandbox_image()  # type: ignore[attr-defined]

    docker.images.get.assert_called_once_with(image)
    docker.images.pull.assert_not_called()


_OPENCODE_PASSWORD = "secret-password-fixture"
_OPENCODE_CONFIG_JSON = '{"providers": {"openai": {"models": {"gpt-4": {}}}}}'


@pytest.fixture
def kwargs() -> ContainerCreateKwargs:
    """
    Legacy (no-proxy) posture. Default for tests/dev without the proxy stack.
    """
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
        opencode_password=_OPENCODE_PASSWORD,
        opencode_config_json=_OPENCODE_CONFIG_JSON,
    )


@pytest.fixture
def proxy_kwargs() -> ContainerCreateKwargs:
    """
    Proxy-enabled posture. Mirrors what production self-host compose deployments
    with ``--include-craft`` produce.

    Note: ``onyx_pat`` is the proxy-injected placeholder because in proxy mode
    the manager's provision flow scrubs the real PAT before reaching this
    builder; the real value lives in Postgres and the proxy injects it on the
    wire. Same for any ``api_key`` in ``opencode_config_json``.
    """
    return build_container_create_kwargs(
        sandbox_id=SANDBOX_ID,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        image="onyxdotapp/sandbox:test",
        onyx_pat=SANDBOX_PROXY_INJECTED_PLACEHOLDER,
        api_server_url="https://onyx.example.com",
        network="onyx_craft_sandbox",
        volume_name="onyx-craft-sandbox-12345678",
        memory_limit="2g",
        cpu_limit=1.0,
        opencode_password=_OPENCODE_PASSWORD,
        opencode_config_json=_OPENCODE_CONFIG_JSON,
        sandbox_proxy_host="sandbox-proxy",
        proxy_ca_volume_name="sandbox_proxy_ca",
    )


def test_container_kwargs_has_required_security_options(
    kwargs: ContainerCreateKwargs,
) -> None:
    """The sandbox must not be privileged or escalate caps."""
    assert kwargs["user"] == "1000:1000"
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["privileged"] is False


def test_sandbox_exec_wrapper_pairs_uid_with_user_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_run = MagicMock(return_value=dsm.ExecResult(0, b"", b""))
    monkeypatch.setattr(dsm, "run_in_container", mock_run)
    container = MagicMock()

    result = dsm._run_in_container_as_sandbox_user(
        container,
        ["/bin/sh", "-c", "id"],
        check=False,
        workdir="/workspace",
    )

    assert result.exit_code == 0
    mock_run.assert_called_once_with(
        container,
        ["/bin/sh", "-c", "id"],
        user=dsm.SANDBOX_EXEC_USER,
        workdir="/workspace",
        environment=dsm.SANDBOX_EXEC_ENV,
        check=False,
    )


def _empty_byte_stream() -> Generator[bytes, None, int]:
    yield from ()
    return 0


def test_sandbox_stream_exec_wrappers_pair_uid_with_user_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_stdin = MagicMock(return_value=dsm.ExecResult(0, b"", b""))
    stream = _empty_byte_stream()
    mock_stdout = MagicMock(return_value=stream)
    monkeypatch.setattr(dsm, "stream_stdin_to_container", mock_stdin)
    monkeypatch.setattr(dsm, "stream_stdout_from_container", mock_stdout)
    container = MagicMock()

    result = dsm._stream_stdin_to_container_as_sandbox_user(
        container,
        ["tar", "-xzf", "-"],
        b"payload",
        workdir="/workspace",
    )
    returned_stream = dsm._stream_stdout_from_container_as_sandbox_user(
        container,
        ["tar", "-czf", "-"],
        workdir="/workspace",
    )

    assert result.exit_code == 0
    assert returned_stream is stream
    mock_stdin.assert_called_once_with(
        container,
        ["tar", "-xzf", "-"],
        b"payload",
        user=dsm.SANDBOX_EXEC_USER,
        workdir="/workspace",
        environment=dsm.SANDBOX_EXEC_ENV,
    )
    mock_stdout.assert_called_once_with(
        container,
        ["tar", "-czf", "-"],
        user=dsm.SANDBOX_EXEC_USER,
        workdir="/workspace",
        environment=dsm.SANDBOX_EXEC_ENV,
        chunk_size=64 * 1024,
    )


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
    # opencode-serve transport wiring
    assert env["OPENCODE_SERVER_PASSWORD"] == _OPENCODE_PASSWORD
    assert env["OPENCODE_CONFIG_CONTENT"] == _OPENCODE_CONFIG_JSON
    # Forbidden env - any storage credential leaking into the sandbox would let
    # the agent read every snapshot/file in the deployment.
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


def test_container_kwargs_does_not_publish_serve_outside_dev(
    kwargs: ContainerCreateKwargs,
) -> None:
    """Compose deployments reach opencode-serve through sandbox bridge DNS."""
    assert kwargs["ports"] == {}


def test_container_kwargs_publishes_serve_on_localhost_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host-run dev workers reach opencode-serve through a local ephemeral port."""
    monkeypatch.setattr(dsm, "DEV_MODE", True)
    kwargs = build_container_create_kwargs(
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
        opencode_password=_OPENCODE_PASSWORD,
        opencode_config_json=_OPENCODE_CONFIG_JSON,
    )
    assert kwargs["ports"] == {
        OPENCODE_SERVE_CONTAINER_PORT: (OPENCODE_SERVE_HOST_BIND_IP, None),
    }


# ------------------------------------------------------------------------------
# Path validators
# ------------------------------------------------------------------------------


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


# ------------------------------------------------------------------------------
# Network / data isolation invariants
# ------------------------------------------------------------------------------


def test_container_kwargs_env_is_a_minimal_allowlist(
    kwargs: ContainerCreateKwargs,
) -> None:
    """Lock the env schema. Adding any new key needs an explicit test update.

    This is the single point where any future contributor could leak a bucket
    name, host, or credential into the sandbox by accident — so we pin the full
    key set.
    """
    env = kwargs["environment"]
    assert isinstance(env, dict)
    assert set(env.keys()) == {
        "ONYX_PAT",
        "ONYX_SERVER_URL",
        "OPENCODE_SERVER_PASSWORD",
        "OPENCODE_CONFIG_CONTENT",
    }


def test_container_kwargs_mounts_only_workspace_sessions(
    kwargs: ContainerCreateKwargs,
) -> None:
    """
    The only host-side resource exposed to the agent is its own workspace
    volume.
    """
    volumes = kwargs["volumes"]
    assert len(volumes) == 1
    only_volume = next(iter(volumes.values()))
    assert only_volume["bind"] == "/workspace/sessions"
    # No bind mounts that could leak host secrets.
    for source in volumes:
        assert not source.startswith("/"), (
            f"Bind mount detected: {source}; only named volumes are allowed"
        )


def test_container_kwargs_mounts_tmp_as_tmpfs(
    kwargs: ContainerCreateKwargs,
) -> None:
    """Expose /tmp as sandbox-local scratch space without adding a host mount."""
    assert kwargs["tmpfs"] == {SANDBOX_TMP_PATH: SANDBOX_TMPFS_OPTIONS}


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
            opencode_password=_OPENCODE_PASSWORD,
            opencode_config_json=_OPENCODE_CONFIG_JSON,
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
            opencode_password=_OPENCODE_PASSWORD,
            opencode_config_json=_OPENCODE_CONFIG_JSON,
        )
    assert not any(
        "looks like an internal compose hostname" in r.getMessage()
        for r in caplog.records
    )


# ------------------------------------------------------------------------------
# Proxy-enabled posture (SANDBOX_PROXY_HOST set)
#
# The proxy posture layers on top of the legacy posture. These tests pin the
# additions so a future refactor can't loosen the bounding-set drop / CA-mount /
# env-allowlist semantics without an explicit test update.
# ------------------------------------------------------------------------------


def test_proxy_kwargs_wraps_entrypoint_in_firewall_init(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """
    Must set ``entrypoint`` (not just ``command``) -- the image bakes
    ENTRYPOINT, and Docker concatenates image-ENTRYPOINT + command-args. Setting
    only ``command`` leaves firewall-init.sh as ignored argv to the image's
    entrypoint.sh; the lockdown silently never runs and the sandbox boots
    without the proxy posture.
    """
    assert proxy_kwargs["entrypoint"] == ["/workspace/firewall-init.sh"]
    assert proxy_kwargs["command"] == ["/workspace/entrypoint.sh"]


def test_legacy_kwargs_do_not_override_entrypoint(
    kwargs: ContainerCreateKwargs,
) -> None:
    """
    Proxy-disabled posture relies on the image's baked ENTRYPOINT to launch
    entrypoint.sh; the manager must NOT set ``entrypoint`` here, or legacy
    dev/test runs would lose the agent-launch path.
    """
    assert "entrypoint" not in kwargs
    assert kwargs["command"] == ["/workspace/entrypoint.sh"]


def test_proxy_kwargs_runs_init_as_root_with_required_caps(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """NET_ADMIN for iptables; SETPCAP authorises the bounding-set drop;
    SETUID + SETGID gate the uid/gid switch under cap_drop=ALL; CHOWN repairs
    the sessions mount-point owner."""
    assert proxy_kwargs["user"] == "0:0"
    assert proxy_kwargs["cap_drop"] == ["ALL"]
    assert proxy_kwargs["cap_add"] == [
        "NET_ADMIN",
        "SETPCAP",
        "SETUID",
        "SETGID",
        "CHOWN",
    ]
    # The other invariants must not regress in proxy mode.
    assert proxy_kwargs["privileged"] is False
    assert "no-new-privileges:true" in proxy_kwargs["security_opt"]


def test_proxy_kwargs_mounts_ca_volume_read_only(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """
    firewall-init.sh's ``CA_SRC`` defaults to ``/sandbox-ca/ca.crt``; the shared
    compose CA volume must mount there RO so the script can install the proxy CA
    into the trust store.
    """
    volumes = proxy_kwargs["volumes"]
    assert "sandbox_proxy_ca" in volumes
    assert volumes["sandbox_proxy_ca"]["bind"] == "/sandbox-ca"
    assert volumes["sandbox_proxy_ca"]["mode"] == "ro"
    # The per-sandbox workspace volume is still there.
    assert "onyx-craft-sandbox-12345678" in volumes


def test_proxy_kwargs_env_contains_proxy_and_ca_keys(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """
    Env must wire HTTPS_PROXY + the SDK CA envs + firewall-init.sh's own
    contract vars.
    """
    env = proxy_kwargs["environment"]
    # The legacy 4-key core is preserved; ONYX_PAT is the proxy placeholder in
    # this posture (real value lives in Postgres, proxy injects on wire).
    assert env["ONYX_PAT"] == SANDBOX_PROXY_INJECTED_PLACEHOLDER
    assert env["ONYX_SERVER_URL"] == "https://onyx.example.com"
    assert env["OPENCODE_SERVER_PASSWORD"] == _OPENCODE_PASSWORD
    assert env["OPENCODE_CONFIG_CONTENT"] == _OPENCODE_CONFIG_JSON
    # firewall-init.sh contract.
    assert env["SANDBOX_PROXY_HOST"] == "sandbox-proxy"
    assert env["SANDBOX_PROXY_PORT"] == "8080"
    assert env["SANDBOX_PROXY_BOOTSTRAP_MODE"] == "entrypoint"
    assert env["SANDBOX_PROXY_CA_BUNDLE_SRC"] == "/sandbox-ca/ca.crt"
    assert env["SANDBOX_PROXY_CA_BUNDLE_DST"] == "/etc/ssl/sandbox/ca-bundle.crt"
    # Proxy wiring (case-doubled — HTTP libs split on which they read).
    assert env["HTTPS_PROXY"] == "http://sandbox-proxy:8080"
    assert env["https_proxy"] == "http://sandbox-proxy:8080"
    assert env["HTTP_PROXY"] == "http://sandbox-proxy:8080"
    assert env["http_proxy"] == "http://sandbox-proxy:8080"
    # NO_PROXY is loopback only; api-server traffic goes through the proxy too.
    assert env["NO_PROXY"] == "127.0.0.1,localhost"
    # Case-doubled like the other proxy vars; HTTP libs split on which they
    # read.
    assert env["no_proxy"] == env["NO_PROXY"]
    # SDK CA envs all point at the bundle the init script writes.
    for key in (
        "NODE_EXTRA_CA_CERTS",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "AWS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "GIT_SSL_CAINFO",
    ):
        assert env[key] == "/etc/ssl/sandbox/ca-bundle.crt", (
            f"SDK CA env var {key} not pointed at the materialised bundle; "
            "the SDK will fall back to its bundled trust store and fail "
            "closed at the iptables lockdown."
        )


def test_proxy_kwargs_env_still_excludes_storage_credentials(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """Layering proxy keys must not loosen the credential-leak prohibition.

    Adding the proxy env is the kind of change that could accidentally drag in
    S3/MinIO env from the surrounding api_server. Lock it down.
    """
    env = proxy_kwargs["environment"]
    forbidden = {
        "S3_AWS_ACCESS_KEY_ID",
        "S3_AWS_SECRET_ACCESS_KEY",
        "MINIO_ROOT_PASSWORD",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "ONYX_SANDBOX_PUSH_PRIVATE_KEY",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
    }
    leaked = forbidden & set(env)
    assert not leaked, f"Storage credentials leaked into sandbox env: {leaked}"


def test_proxy_kwargs_env_is_a_locked_allowlist(
    proxy_kwargs: ContainerCreateKwargs,
) -> None:
    """
    Pin the full proxy-posture env key set. Adding a new key needs an explicit
    test update.
    """
    env = proxy_kwargs["environment"]
    assert set(env.keys()) == {
        # Legacy core
        "ONYX_PAT",
        "ONYX_SERVER_URL",
        "OPENCODE_SERVER_PASSWORD",
        "OPENCODE_CONFIG_CONTENT",
        # firewall-init.sh contract
        "SANDBOX_PROXY_HOST",
        "SANDBOX_PROXY_PORT",
        "SANDBOX_PROXY_BOOTSTRAP_MODE",
        "SANDBOX_PROXY_CA_BUNDLE_SRC",
        "SANDBOX_PROXY_CA_BUNDLE_DST",
        # Agent-side proxy + CA wiring
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "https_proxy",
        "http_proxy",
        "NO_PROXY",
        "no_proxy",
        "NODE_EXTRA_CA_CERTS",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "AWS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "GIT_SSL_CAINFO",
        "GH_TOKEN",
        "GH_NO_UPDATE_NOTIFIER",
    }


def test_no_proxy_kwargs_omit_cap_add(kwargs: ContainerCreateKwargs) -> None:
    """
    The no-proxy posture must NOT carry cap_add; NET_ADMIN out of nowhere would
    be a real escalation.
    """
    assert kwargs.get("cap_add", []) == []


def test_no_proxy_kwargs_keep_legacy_command(kwargs: ContainerCreateKwargs) -> None:
    """The no-proxy posture skips firewall-init.sh entirely."""
    assert kwargs["command"] == ["/workspace/entrypoint.sh"]


def test_proxy_kwargs_requires_ca_volume() -> None:
    """Proxy posture needs the CA volume when the proxy host is set."""
    with pytest.raises(ValueError, match="Proxy posture requires both"):
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
            opencode_password=_OPENCODE_PASSWORD,
            opencode_config_json=_OPENCODE_CONFIG_JSON,
            sandbox_proxy_host="sandbox-proxy",
            proxy_ca_volume_name=None,
        )
