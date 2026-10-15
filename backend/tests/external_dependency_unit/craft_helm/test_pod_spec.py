"""Render the immutable guest bootstrap and sandbox privilege boundaries."""

from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart


def _spec(extra_args: list[str] | None = None) -> dict[str, Any]:
    rendered = render_chart(extra_args)
    assert rendered.returncode == 0, rendered.stderr
    resources: list[dict[str, Any]] = [
        resource for resource in yaml.safe_load_all(rendered.stdout) if resource
    ]
    return next(
        resource["template"]["spec"]
        for resource in resources
        if resource["kind"] == "PodTemplate"
        and resource["metadata"]["name"] == "sandbox-pod"
    )


@pytest.mark.parametrize(
    ("extra_args", "image", "pull_policy"),
    [
        (
            ["--set", "global.version=v9.8.7"],
            "onyxdotapp/sandbox:v9.8.7",
            "IfNotPresent",
        ),
        (
            [
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=onyxdotapp/sandbox:local",
            ],
            "onyxdotapp/sandbox:local",
            "IfNotPresent",
        ),
        (
            ["--set", "configMap.SANDBOX_IMAGE_PULL_POLICY=Always"],
            "onyxdotapp/sandbox:latest",
            "Always",
        ),
        (
            [
                "--set-string",
                "configMap.SANDBOX_CONTAINER_IMAGE=registry.example/sandbox:proof",
            ],
            "registry.example/sandbox:proof",
            "IfNotPresent",
        ),
    ],
)
def test_bootstrap_and_main_container_use_the_same_image(
    extra_args: list[str], image: str, pull_policy: str
) -> None:
    spec = _spec(["--set-string", "configMap.SANDBOX_CONTAINER_IMAGE=", *extra_args])
    for container in [*spec["containers"], *spec["initContainers"]]:
        assert container["image"] == image
        assert container["imagePullPolicy"] == pull_policy


def test_single_guest_container_has_only_firewall_init() -> None:
    spec = _spec()
    assert spec["runtimeClassName"] == "kata-fc"
    assert [container["name"] for container in spec["containers"]] == ["sandbox"]
    assert [container["name"] for container in spec["initContainers"]] == [
        "sandbox-firewall"
    ]
    firewall = spec["initContainers"][0]
    assert firewall["command"] == [
        "/bin/bash",
        "/opt/onyx-guest/firewall-init.sh",
        "firewall",
    ]
    assert "restartPolicy" not in firewall
    assert spec["containers"][0]["readinessProbe"]["tcpSocket"]["port"] == 4096
    assert spec["containers"][0]["startupProbe"]["tcpSocket"]["port"] == 4096


def test_capabilities_are_split_between_firewall_and_guest_supervisor() -> None:
    spec = _spec()
    firewall = spec["initContainers"][0]["securityContext"]
    main = spec["containers"][0]["securityContext"]
    for context in (firewall, main):
        assert context["runAsUser"] == 0
        assert context["allowPrivilegeEscalation"] is False
        assert context["privileged"] is False
        assert context["capabilities"]["drop"] == ["ALL"]
    assert set(firewall["capabilities"]["add"]) == {"NET_ADMIN"}
    assert set(main["capabilities"]["add"]) == {"SETUID", "SETGID", "SETPCAP", "CHOWN"}
    assert spec["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert "fsGroup" not in spec["securityContext"]


def test_guest_has_no_host_namespaces_service_token_or_host_mounts() -> None:
    spec = _spec()
    assert spec["automountServiceAccountToken"] is False
    assert spec["enableServiceLinks"] is False
    for setting in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
        assert spec[setting] is False
    assert all("hostPath" not in volume for volume in spec["volumes"])
    for mount in spec["containers"][0].get("volumeMounts", []):
        assert not mount["mountPath"].startswith("/opt/onyx-guest")
        assert mount["mountPath"] != "/workspace"


def test_guest_receives_proxy_placeholders_without_storage_or_push_keys() -> None:
    spec = _spec()
    env = {entry["name"]: entry.get("value") for entry in spec["containers"][0]["env"]}
    assert env["ONYX_PAT"] == "replaced_by_egress_proxy"
    assert env["GH_TOKEN"] == "replaced_by_egress_proxy"
    assert env["ONYX_API_PREFIX"] == ""
    assert env["SANDBOX_PROXY_HOST"]
    assert env["SANDBOX_PROXY_PORT"] == "8080"
    assert env["OPENCODE_DATA_HOME"] == "/workspace/opencode-data"
    assert not any(
        name.startswith(("S3_", "POSTGRES_", "REDIS_", "ONYX_SANDBOX_PUSH"))
        for name in env
    )
    assert not {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
    }.intersection(env)
    ports = {port["containerPort"] for port in spec["containers"][0]["ports"]}
    assert 4096 in ports
    assert 8731 not in ports
    assert set(range(3010, 3100)).issubset(ports)
