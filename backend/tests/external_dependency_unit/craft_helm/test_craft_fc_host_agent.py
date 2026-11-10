"""Render tests for the Craft Firecracker host agent (craft.sandboxRuntime).

Everything is off by default. With firecracker on, the agent must land on the
Firecracker sandbox nodes with the host access it needs, and its pods may reach
sandbox-proxy. A wrong render here fails only at runtime on a KVM node."""

from typing import Any

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import (
    render_chart,
    skip_or_fail,
)

_TEMPLATE = "templates/craft-fc-host-agent.yaml"
_CONFIGMAP_TEMPLATE = "templates/configmap.yaml"
_PROXY_POLICY_TEMPLATE = "templates/sandbox-proxy/networkpolicy.yaml"
_PODTEMPLATE_TEMPLATE = "templates/sandbox-podtemplate.yaml"
# The pods that call the agents get the mTLS client certificate.
_CLIENT_TEMPLATES = [
    "templates/api-deployment.yaml",
    "templates/celery-worker-heavy.yaml",
    "templates/celery-worker-scheduled-tasks.yaml",
]
_CLIENT_DIR = "/etc/onyx/craft-fc-agent-client"
_AGENT_NS = "onyx-sandbox-runtime"
_FIRECRACKER = [
    "--set",
    "craft.sandboxRuntime=firecracker",
    "--set-string",
    "craft.hostAgent.image.tag=0.1.0",
    "--set-string",
    "craft.hostAgent.tls.existingSecret=host-agent-tls",
    "--set-string",
    "craft.hostAgent.client.existingSecret=agent-client",
    "--set",
    "auth.sandboxNodeRegistration.enabled=true",
    "--set-string",
    "auth.sandboxNodeRegistration.values.sandbox_node_registration_secret=reg-test",
]


def _render(extra_args: list[str], template: str = _TEMPLATE) -> list[dict[str, Any]]:
    """Rendered documents, or [] when the template renders nothing."""
    result = render_chart([*extra_args, "--show-only", template])
    if result.returncode != 0:
        # --show-only on an empty template is a helm error, not empty output.
        if "could not find template" in result.stderr:
            return []
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def _by_kind(docs: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind)


def _configmap_data(extra_args: list[str]) -> dict[str, str]:
    return _render(extra_args, _CONFIGMAP_TEMPLATE)[0]["data"]


def _proxy_ingress_sources(extra_args: list[str]) -> list[dict[str, Any]]:
    policy = _render(extra_args, _PROXY_POLICY_TEMPLATE)[0]
    return policy["spec"]["ingress"][0]["from"]


def _ns_selector(namespace: str) -> dict[str, Any]:
    return {"matchLabels": {"kubernetes.io/metadata.name": namespace}}


def test_pod_runtime_renders_nothing_new() -> None:
    assert _render([]) == []
    assert "SANDBOX_RUNTIME" not in _configmap_data([])
    assert _proxy_ingress_sources([]) == [
        {"namespaceSelector": _ns_selector("onyx-sandboxes")}
    ]


def test_firecracker_wires_sandbox_runtime_once() -> None:
    data = _configmap_data(
        [*_FIRECRACKER, "--set-string", "configMap.SANDBOX_RUNTIME=pod"]
    )
    assert data["SANDBOX_RUNTIME"] == "firecracker"


def test_agent_namespace_is_privileged() -> None:
    namespace = _by_kind(_render(_FIRECRACKER), "Namespace")
    assert namespace["metadata"]["name"] == _AGENT_NS
    labels = namespace["metadata"]["labels"]
    for mode in ("enforce", "audit", "warn"):
        assert labels[f"pod-security.kubernetes.io/{mode}"] == "privileged"


def test_agent_pod_spec() -> None:
    docs = _render(_FIRECRACKER)
    daemonset = _by_kind(docs, "DaemonSet")
    spec = daemonset["spec"]["template"]["spec"]
    sandbox = _render(_FIRECRACKER, _PODTEMPLATE_TEMPLATE)[0]["template"]["spec"]
    container = spec["containers"][0]
    mounts = {m["name"]: m for m in container["volumeMounts"]}
    volumes = {v["name"]: v for v in spec["volumes"]}
    env = {e["name"]: e for e in container["env"]}

    assert daemonset["metadata"]["namespace"] == _AGENT_NS
    # The sandbox nodes that Terraform marked for Firecracker, never the
    # sandbox RuntimeClass.
    assert spec["nodeSelector"] == {**sandbox["nodeSelector"], "onyx.app/kvm": "true"}
    assert spec["tolerations"] == sandbox["tolerations"]
    assert "runtimeClassName" not in spec
    assert spec["hostPID"] is True
    # The drain watch reads the Node: the token of the agent's own account.
    assert spec["automountServiceAccountToken"] is True
    assert spec["serviceAccountName"] == "onyx-craft-fc-host-agent"
    assert container["securityContext"]["privileged"] is True
    assert container["image"] == "onyxdotapp/craft-fc-host-agent:0.1.0"
    # Host cgroup namespace, so the agent can check VM cgroups on re-adopt.
    assert container["command"] == [
        "nsenter",
        "--target=1",
        "--cgroup",
        "--",
        "/usr/local/bin/host-agent",
    ]
    assert container["resources"]["requests"] == {"cpu": "250m", "memory": "256Mi"}

    # The jailer runs in the host mount namespace: same path on both sides.
    assert mounts["data"]["mountPath"] == "/var/lib/craft-fc"
    assert volumes["data"]["hostPath"] == {
        "path": "/var/lib/craft-fc",
        "type": "DirectoryOrCreate",
    }
    assert volumes["kvm"]["hostPath"] == {"path": "/dev/kvm", "type": "CharDevice"}
    assert volumes["tls"]["secret"]["secretName"] == "host-agent-tls"
    assert mounts["tls"]["readOnly"] is True

    args = container["args"]
    assert "--data-dir=/var/lib/craft-fc" in args
    assert "--listen=:7443" in args
    assert "--client-ca=/etc/craft-fc/tls/ca.crt" in args
    assert "--tls-cert=/etc/craft-fc/tls/tls.crt" in args
    assert "--tls-key=/etc/craft-fc/tls/tls.key" in args
    assert "--uid-base=1000000" in args
    assert "--uid-count=65536" in args
    assert "--dial-ports=3010,9222" in args
    assert "--relay-max-conns=256" in args
    assert "--dial-max-streams=64" in args
    assert not [a for a in args if a.startswith("--client-allowed-sans")]
    # The agent joins $POD_IP and the listen port itself (it brackets IPv6).
    assert not [a for a in args if a.startswith("--advertise-address")]
    assert env["POD_IP"]["valueFrom"]["fieldRef"]["fieldPath"] == "status.podIP"
    assert "--egress-proxy=onyx-sandbox-proxy.onyx.svc.cluster.local:8080" in args
    assert any(a.startswith("--api-server-url=http") for a in args)
    assert env["NODE_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "spec.nodeName"
    assert "--watch-node-drain" in args
    assert "--drain-taints=node.kubernetes.io/unschedulable" in args
    assert "--drain-poll-interval=10s" in args


def test_drain_watch_rbac_is_get_nodes_only() -> None:
    docs = _render(_FIRECRACKER)
    account = _by_kind(docs, "ServiceAccount")
    role = _by_kind(docs, "ClusterRole")
    binding = _by_kind(docs, "ClusterRoleBinding")

    assert account["metadata"]["namespace"] == _AGENT_NS
    assert role["rules"] == [
        {"apiGroups": [""], "resources": ["nodes"], "verbs": ["get"]}
    ]
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": account["metadata"]["name"],
            "namespace": _AGENT_NS,
        }
    ]


def test_drain_watch_off_has_no_rbac() -> None:
    docs = _render([*_FIRECRACKER, "--set", "craft.hostAgent.drainWatch.enabled=false"])
    kinds = {d["kind"] for d in docs}
    spec = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]
    args = spec["containers"][0]["args"]

    assert not kinds & {"ServiceAccount", "ClusterRole", "ClusterRoleBinding"}
    assert spec["automountServiceAccountToken"] is False
    assert "serviceAccountName" not in spec
    assert not [a for a in args if "drain" in a]


def test_drain_watch_overrides() -> None:
    docs = _render(
        [
            *_FIRECRACKER,
            "--set-string",
            "craft.hostAgent.drainWatch.taints=node.kubernetes.io/unschedulable\\,karpenter.sh/disrupted",
            "--set-string",
            "craft.hostAgent.drainWatch.pollInterval=30s",
        ]
    )
    args = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["containers"][0][
        "args"
    ]

    assert (
        "--drain-taints=node.kubernetes.io/unschedulable,karpenter.sh/disrupted" in args
    )
    assert "--drain-poll-interval=30s" in args


def test_registration_secret_is_copied_into_agent_namespace() -> None:
    docs = _render(_FIRECRACKER)
    secret = _by_kind(docs, "Secret")
    container = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["containers"][0]
    ref = next(
        e for e in container["env"] if e["name"] == "SANDBOX_NODE_REGISTRATION_SECRET"
    )

    assert secret["metadata"]["namespace"] == _AGENT_NS
    assert secret["stringData"] == {"sandbox_node_registration_secret": "reg-test"}
    assert ref["valueFrom"]["secretKeyRef"] == {
        "name": secret["metadata"]["name"],
        "key": "sandbox_node_registration_secret",
    }


def test_registration_existing_secret_is_not_copied() -> None:
    docs = _render(
        [
            *_FIRECRACKER,
            "--set-string",
            "craft.hostAgent.registrationExistingSecret=agent-reg",
        ]
    )
    container = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["containers"][0]
    ref = next(
        e for e in container["env"] if e["name"] == "SANDBOX_NODE_REGISTRATION_SECRET"
    )

    assert not [d for d in docs if d["kind"] == "Secret"]
    assert ref["valueFrom"]["secretKeyRef"]["name"] == "agent-reg"


def test_agent_overrides() -> None:
    docs = _render(
        [
            *_FIRECRACKER,
            "--set-string",
            "craft.hostAgent.nodeSelector.pool=fc",
            "--set",
            "craft.hostAgent.createNamespace=false",
            "--set",
            "craft.hostAgent.uidBase=2000000",
            "--set",
            "craft.hostAgent.relayMaxConns=64",
            "--set-string",
            "craft.hostAgent.apiServerUrl=https://api.example",
            "--set",
            "craft.hostAgent.dialMaxStreams=8",
            "--set-string",
            "craft.hostAgent.clientAllowedSans=spiffe://onyx/api-server",
            "--set-string",
            "craft.hostAgent.advertiseAddress=agent.example:7443",
        ]
    )
    spec = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]
    args = spec["containers"][0]["args"]

    assert not [d for d in docs if d["kind"] == "Namespace"]
    assert spec["nodeSelector"] == {"pool": "fc"}
    assert "--uid-base=2000000" in args
    assert "--relay-max-conns=64" in args
    assert "--api-server-url=https://api.example" in args
    assert "--dial-max-streams=8" in args
    assert "--client-allowed-sans=spiffe://onyx/api-server" in args
    assert "--advertise-address=agent.example:7443" in args


def test_headless_service_targets_agent_pods() -> None:
    docs = _render(_FIRECRACKER)
    service = _by_kind(docs, "Service")
    pod_labels = _by_kind(docs, "DaemonSet")["spec"]["template"]["metadata"]["labels"]

    assert service["metadata"]["namespace"] == _AGENT_NS
    assert service["spec"]["clusterIP"] == "None"
    assert service["spec"]["selector"].items() <= pod_labels.items()
    assert service["spec"]["ports"][0]["port"] == 7443


def test_agent_pods_reach_sandbox_proxy() -> None:
    sources = _proxy_ingress_sources(_FIRECRACKER)
    pod_labels = _by_kind(_render(_FIRECRACKER), "DaemonSet")["spec"]["template"][
        "metadata"
    ]["labels"]

    # Pod sandboxes keep their access; agent pods are added.
    assert sources[0] == {"namespaceSelector": _ns_selector("onyx-sandboxes")}
    assert sources[1]["namespaceSelector"] == _ns_selector(_AGENT_NS)
    assert sources[1]["podSelector"]["matchLabels"].items() <= pod_labels.items()
    assert len(sources) == 2


def test_only_agent_clients_reach_agent_listener() -> None:
    policy = _by_kind(_render(_FIRECRACKER), "NetworkPolicy")
    rule = policy["spec"]["ingress"][0]

    assert policy["metadata"]["namespace"] == _AGENT_NS
    assert policy["spec"]["policyTypes"] == ["Ingress"]
    assert rule["from"] == [
        {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "onyx"}
            },
            "podSelector": {"matchLabels": {"app": app}},
        }
        for app in (
            "api-server",
            "celery-worker-heavy",
            "celery-worker-scheduled-tasks",
        )
    ]
    assert rule["ports"] == [{"protocol": "TCP", "port": 7443}]


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--set-string", "craft.hostAgent.image.tag="], "craft.hostAgent.image.tag"),
        (
            ["--set-string", "craft.hostAgent.tls.existingSecret="],
            "craft.hostAgent.tls.existingSecret",
        ),
        (
            ["--set", "auth.sandboxNodeRegistration.enabled=false"],
            "auth.sandboxNodeRegistration.enabled",
        ),
        (
            ["--set-string", "auth.sandboxNodeRegistration.existingSecret=reg"],
            "craft.hostAgent.registrationExistingSecret",
        ),
        (["--set-string", "configMap.ENABLE_CRAFT=false"], "ENABLE_CRAFT"),
        (
            ["--set-string", "craft.hostAgent.namespace=onyx"],
            "craft.hostAgent.namespace",
        ),
        (["--set", "craft.sandboxRuntime=kata"], "craft.sandboxRuntime"),
        (
            ["--set-string", "craft.hostAgent.client.existingSecret="],
            "craft.hostAgent.client.existingSecret",
        ),
    ],
)
def test_firecracker_fails_closed(extra_args: list[str], message: str) -> None:
    result = render_chart([*_FIRECRACKER, *extra_args, "--show-only", _TEMPLATE])
    assert result.returncode != 0
    assert message in result.stderr


def test_registration_key_follows_secret_keys() -> None:
    """A secretKeys override changes the key the api_server reads; the agent
    copy and its secretKeyRef must use the same key."""
    docs = _render(
        [
            *_FIRECRACKER,
            "--set-string",
            "auth.sandboxNodeRegistration.secretKeys.SANDBOX_NODE_REGISTRATION_SECRET=custom_key",
            "--set-string",
            "auth.sandboxNodeRegistration.values.custom_key=reg-custom",
        ]
    )
    secret = _by_kind(docs, "Secret")
    container = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["containers"][0]
    ref = next(
        e for e in container["env"] if e["name"] == "SANDBOX_NODE_REGISTRATION_SECRET"
    )

    assert secret["stringData"] == {"custom_key": "reg-custom"}
    assert ref["valueFrom"]["secretKeyRef"]["key"] == "custom_key"


def test_image_pull_secrets_come_from_agent_values() -> None:
    """Release pull secrets live in the release namespace, so the agent pods
    use only craft.hostAgent.imagePullSecrets (in the agent namespace)."""
    release_only = _by_kind(
        _render([*_FIRECRACKER, "--set", "imagePullSecrets[0].name=release-cred"]),
        "DaemonSet",
    )["spec"]["template"]["spec"]
    assert "imagePullSecrets" not in release_only

    agent = _by_kind(
        _render(
            [
                *_FIRECRACKER,
                "--set",
                "craft.hostAgent.imagePullSecrets[0].name=agent-cred",
            ]
        ),
        "DaemonSet",
    )["spec"]["template"]["spec"]
    assert agent["imagePullSecrets"] == [{"name": "agent-cred"}]


def _client_container(
    extra_args: list[str], template: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(pod spec, first container) of a Deployment template."""
    spec = _render(extra_args, template)[0]["spec"]["template"]["spec"]
    return spec, spec["containers"][0]


@pytest.mark.parametrize("template", _CLIENT_TEMPLATES)
def test_agent_clients_get_mtls_files(template: str) -> None:
    """The env names match backend/onyx/microvm/configs.py; the files come
    from craft.hostAgent.client.existingSecret."""
    spec, container = _client_container(
        [
            *_FIRECRACKER,
            "--set-string",
            "craft.hostAgent.client.tlsServerName=agent.onyx.internal",
        ],
        template,
    )
    env = {e["name"]: e.get("value") for e in container["env"]}
    mounts = {m["name"]: m for m in container["volumeMounts"]}
    volumes = {v["name"]: v for v in spec["volumes"]}

    assert env["SANDBOX_FC_AGENT_CLIENT_CERT_PATH"] == f"{_CLIENT_DIR}/tls.crt"
    assert env["SANDBOX_FC_AGENT_CLIENT_KEY_PATH"] == f"{_CLIENT_DIR}/tls.key"
    assert env["SANDBOX_FC_AGENT_CA_PATH"] == f"{_CLIENT_DIR}/ca.crt"
    assert env["SANDBOX_FC_AGENT_TLS_SERVER_NAME"] == "agent.onyx.internal"
    assert mounts["craft-fc-agent-client"] == {
        "name": "craft-fc-agent-client",
        "mountPath": _CLIENT_DIR,
        "readOnly": True,
    }
    assert volumes["craft-fc-agent-client"]["secret"]["secretName"] == "agent-client"


@pytest.mark.parametrize("template", _CLIENT_TEMPLATES)
def test_agent_client_keeps_pod_volumes(template: str) -> None:
    values = template.removeprefix("templates/").removesuffix(".yaml")
    key = {
        "api-deployment": "api",
        "celery-worker-heavy": "celery_worker_heavy",
        "celery-worker-scheduled-tasks": "celery_worker_scheduled_tasks",
    }[values]
    spec, container = _client_container(
        [
            *_FIRECRACKER,
            "--set",
            f"{key}.volumes[0].name=extra",
            "--set",
            f"{key}.volumes[0].emptyDir.medium=Memory",
            "--set",
            f"{key}.volumeMounts[0].name=extra",
            "--set",
            f"{key}.volumeMounts[0].mountPath=/extra",
        ],
        template,
    )
    assert {"extra", "craft-fc-agent-client"} <= {v["name"] for v in spec["volumes"]}
    assert {"extra", "craft-fc-agent-client"} <= {
        m["name"] for m in container["volumeMounts"]
    }


@pytest.mark.parametrize("template", _CLIENT_TEMPLATES)
def test_pod_runtime_has_no_agent_client(template: str) -> None:
    spec, container = _client_container([], template)
    env_names = {e["name"] for e in container.get("env", [])}

    assert not {n for n in env_names if n.startswith("SANDBOX_FC_AGENT_")}
    assert "craft-fc-agent-client" not in {v["name"] for v in spec.get("volumes", [])}
