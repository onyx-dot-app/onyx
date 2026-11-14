"""Render tests for the Craft Firecracker release defaults: the agent image,
root drive and SANDBOX_FC_TEMPLATE follow the Onyx release tag, and the chart
makes the agent mTLS certificates when no existingSecret is set."""

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from tests.external_dependency_unit.craft_helm.fake_kube_api import (
    FakeKubeApi,
    fake_kube_api,
)
from tests.external_dependency_unit.craft_helm.rendering import render_chart
from tests.external_dependency_unit.craft_helm.test_craft_fc_host_agent import (
    _AGENT_NS,
    _CLIENT_DIR,
    _CLIENT_TEMPLATES,
    _TEMPLATE,
    _by_kind,
    _configmap_data,
    _render,
)

# Firecracker on, with no image tags and no certificate Secrets.
_BASE = [
    "--set",
    "craft.sandboxRuntime=firecracker",
    "--set",
    "auth.sandboxNodeRegistration.enabled=true",
    "--set-string",
    "auth.sandboxNodeRegistration.values.sandbox_node_registration_secret=reg-test",
]
_RELEASE = [*_BASE, "--set-string", "global.version=v5.2.0"]
_EXISTING = [
    "--set-string",
    "craft.hostAgent.tls.existingSecret=host-agent-tls",
    "--set-string",
    "craft.hostAgent.client.existingSecret=agent-client",
]
_AGENT_SECRET = "onyx-craft-fc-host-agent-tls"
_CLIENT_SECRET = "onyx-craft-fc-host-agent-client-tls"
_AGENT_DNS = f"onyx-craft-fc-host-agent.{_AGENT_NS}.svc"


def _pod_spec(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]


def _tls_secrets(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        d["metadata"]["name"]: d
        for d in docs
        if d["kind"] == "Secret" and d.get("type") == "kubernetes.io/tls"
    }


def _cert(secret: dict[str, Any], key: str) -> x509.Certificate:
    return x509.load_pem_x509_certificate(base64.b64decode(secret["data"][key]))


def _dns_names(cert: x509.Certificate) -> list[str]:
    return cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName)


@pytest.mark.parametrize("version", ["v5.2.0", "v5.2.0-dev"])
def test_versions_follow_the_release_tag(version: str) -> None:
    args = [*_BASE, "--set-string", f"global.version={version}"]
    spec = _pod_spec(_render(args))

    assert spec["containers"][0]["image"] == "onyxdotapp/craft-fc-host-agent:v5.2.0"
    assert spec["initContainers"][0]["image"] == (
        "onyxdotapp/craft-fc-artifacts:rootfs-v5.2.0"
    )
    assert _configmap_data(args)["SANDBOX_FC_TEMPLATE"] == "v5.2.0"


def test_rootfs_version_moves_the_drive_and_the_template() -> None:
    args = [*_RELEASE, "--set-string", "craft.hostAgent.rootfs.version=v5.1.3"]
    spec = _pod_spec(_render(args))

    assert spec["containers"][0]["image"] == "onyxdotapp/craft-fc-host-agent:v5.2.0"
    assert spec["initContainers"][0]["image"] == (
        "onyxdotapp/craft-fc-artifacts:rootfs-v5.1.3"
    )
    assert _configmap_data(args)["SANDBOX_FC_TEMPLATE"] == "v5.1.3"


def test_explicit_tags_need_no_release_tag() -> None:
    """Pinned image tags and template keep working on a floating global.version."""
    args = [
        *_BASE,
        "--set-string",
        "global.version=latest",
        "--set-string",
        "craft.hostAgent.image.tag=0.5.0",
        "--set-string",
        "craft.hostAgent.rootfs.image.tag=rootfs-0.2.1",
        "--set-string",
        "configMap.SANDBOX_FC_TEMPLATE=dev-build-craft-fc-56750c9",
    ]
    spec = _pod_spec(_render(args))

    assert spec["containers"][0]["image"] == "onyxdotapp/craft-fc-host-agent:0.5.0"
    assert spec["initContainers"][0]["image"] == (
        "onyxdotapp/craft-fc-artifacts:rootfs-0.2.1"
    )
    assert _configmap_data(args)["SANDBOX_FC_TEMPLATE"] == "dev-build-craft-fc-56750c9"


def test_pod_runtime_sets_no_template() -> None:
    assert "SANDBOX_FC_TEMPLATE" not in _configmap_data([])


@pytest.mark.parametrize(
    ("extra_args", "template", "message"),
    [
        # Default global.version is "latest": no drive is published for it.
        ([], _TEMPLATE, "pinned root drive version"),
        ([], "templates/configmap.yaml", "pinned root drive version"),
        (["--set-string", "global.version=edge"], _TEMPLATE, "edge"),
        (
            [
                "--set-string",
                "global.version=latest",
                "--set-string",
                "craft.hostAgent.rootfs.image.tag=rootfs-0.2.1",
                "--set-string",
                "configMap.SANDBOX_FC_TEMPLATE=t",
            ],
            _TEMPLATE,
            "craft.hostAgent.image.tag",
        ),
        (
            [
                "--set-string",
                "global.version=v5.2.0",
                "--set-string",
                "craft.hostAgent.rootfs.version=latest",
            ],
            _TEMPLATE,
            "craft.hostAgent.rootfs.version",
        ),
        (
            # The template tag of a hand-picked drive is unknown.
            [
                "--set-string",
                "global.version=v5.2.0",
                "--set-string",
                "craft.hostAgent.rootfs.image.tag=rootfs-0.2.1",
            ],
            _TEMPLATE,
            "configMap.SANDBOX_FC_TEMPLATE",
        ),
    ],
)
def test_floating_release_tag_fails(
    extra_args: list[str], template: str, message: str
) -> None:
    result = render_chart([*_BASE, *extra_args, "--show-only", template])
    assert result.returncode != 0
    assert message in result.stderr


def test_chart_makes_the_mtls_certificates() -> None:
    docs = _render(_RELEASE)
    secrets = _tls_secrets(docs)
    agent, client = secrets[_AGENT_SECRET], secrets[_CLIENT_SECRET]

    assert agent["metadata"]["namespace"] == _AGENT_NS
    assert client["metadata"]["namespace"] == "onyx"
    # One CA signs both sides.
    assert agent["data"]["ca.crt"] == client["data"]["ca.crt"]
    ca = _cert(agent, "ca.crt")
    server_cert = _cert(agent, "tls.crt")
    client_cert = _cert(client, "tls.crt")
    for leaf in (server_cert, client_cert):
        leaf.verify_directly_issued_by(ca)
    assert _dns_names(server_cert) == [_AGENT_DNS, f"{_AGENT_DNS}.cluster.local"]
    assert (
        ExtendedKeyUsageOID.SERVER_AUTH
        in server_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert (
        ExtendedKeyUsageOID.CLIENT_AUTH
        in client_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert {"tls.crt", "tls.key", "ca.crt"} == set(agent["data"]) == set(client["data"])

    tls_volume = next(v for v in _pod_spec(docs)["volumes"] if v["name"] == "tls")
    assert tls_volume["secret"]["secretName"] == _AGENT_SECRET


def test_agents_accept_only_the_chart_made_client_certificate() -> None:
    docs = _render(_RELEASE)
    secrets = _tls_secrets(docs)
    server_cert = _cert(secrets[_AGENT_SECRET], "tls.crt")
    client_names = _dns_names(_cert(secrets[_CLIENT_SECRET], "tls.crt"))
    args = _pod_spec(docs)["containers"][0]["args"]

    # The agent certificate also has the client usage and the same CA, so
    # without the pin one node's agent certificate opens every other agent.
    assert (
        ExtendedKeyUsageOID.CLIENT_AUTH
        in server_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert client_names == ["onyx-craft-fc-client.onyx.svc"]
    assert f"--client-allowed-sans={client_names[0]}" in args
    assert not set(client_names) & set(_dns_names(server_cert))

    override = _pod_spec(
        _render(
            [
                *_RELEASE,
                "--set-string",
                "craft.hostAgent.clientAllowedSans=spiffe://onyx/api-server",
            ]
        )
    )["containers"][0]["args"]
    assert [a for a in override if a.startswith("--client-allowed-sans")] == [
        "--client-allowed-sans=spiffe://onyx/api-server"
    ]


@pytest.mark.parametrize("template", _CLIENT_TEMPLATES)
def test_clients_use_the_chart_made_certificate(template: str) -> None:
    spec = _render(_RELEASE, template)[0]["spec"]["template"]["spec"]
    env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
    volumes = {v["name"]: v for v in spec["volumes"]}

    assert env["SANDBOX_FC_AGENT_CLIENT_CERT_PATH"] == f"{_CLIENT_DIR}/tls.crt"
    assert env["SANDBOX_FC_AGENT_TLS_SERVER_NAME"] == _AGENT_DNS
    assert volumes["craft-fc-agent-client"]["secret"]["secretName"] == _CLIENT_SECRET


def test_tls_server_name_is_added_to_the_chart_made_certificate() -> None:
    args = [
        *_RELEASE,
        "--set-string",
        "craft.hostAgent.client.tlsServerName=agent.example.internal",
    ]
    agent = _tls_secrets(_render(args))[_AGENT_SECRET]

    assert "agent.example.internal" in _dns_names(_cert(agent, "tls.crt"))
    env = {
        e["name"]: e.get("value")
        for e in _render(args, _CLIENT_TEMPLATES[0])[0]["spec"]["template"]["spec"][
            "containers"
        ][0]["env"]
    }
    assert env["SANDBOX_FC_AGENT_TLS_SERVER_NAME"] == "agent.example.internal"


def test_existing_secrets_are_used_unchanged() -> None:
    docs = _render([*_RELEASE, *_EXISTING])
    tls_volume = next(v for v in _pod_spec(docs)["volumes"] if v["name"] == "tls")
    spec = _render([*_RELEASE, *_EXISTING], _CLIENT_TEMPLATES[0])[0]["spec"][
        "template"
    ]["spec"]
    env = {e["name"] for e in spec["containers"][0]["env"]}
    volumes = {v["name"]: v for v in spec["volumes"]}

    assert _tls_secrets(docs) == {}
    assert tls_volume["secret"]["secretName"] == "host-agent-tls"
    assert volumes["craft-fc-agent-client"]["secret"]["secretName"] == "agent-client"
    # Own PKI: the chart sets no server name unless asked.
    assert "SANDBOX_FC_AGENT_TLS_SERVER_NAME" not in env


@pytest.mark.parametrize(
    "secret_value",
    [
        "craft.hostAgent.tls.existingSecret=host-agent-tls",
        "craft.hostAgent.client.existingSecret=agent-client",
    ],
)
def test_one_existing_secret_alone_fails(secret_value: str) -> None:
    result = render_chart(
        [*_RELEASE, "--set-string", secret_value, "--show-only", _TEMPLATE]
    )
    assert result.returncode != 0
    assert "set both craft.hostAgent.tls.existingSecret" in result.stderr


def test_loop_store_size_sets_the_agent_env() -> None:
    def env(extra: list[str]) -> dict[str, Any]:
        container = _pod_spec(_render([*_RELEASE, *extra]))["containers"][0]
        return {e["name"]: e.get("value") for e in container["env"]}

    assert "CRAFT_FC_LOOP_STORE_GIB" not in env([])
    sized = env(["--set", "craft.hostAgent.loopStore.sizeGiB=200"])
    assert sized["CRAFT_FC_LOOP_STORE_GIB"] == "200"


def test_loop_store_size_must_be_whole_gib() -> None:
    result = render_chart(
        [
            *_RELEASE,
            "--set-string",
            "craft.hostAgent.loopStore.sizeGiB=1.5T",
            "--show-only",
            _TEMPLATE,
        ]
    )
    assert result.returncode != 0
    assert "craft.hostAgent.loopStore.sizeGiB" in result.stderr


def test_ip_tls_server_name_is_an_ip_san() -> None:
    args = [*_RELEASE, "--set-string", "craft.hostAgent.client.tlsServerName=10.0.0.5"]
    cert = _cert(_tls_secrets(_render(args))[_AGENT_SECRET], "tls.crt")
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

    assert [str(ip) for ip in sans.get_values_for_type(x509.IPAddress)] == ["10.0.0.5"]
    assert "10.0.0.5" not in sans.get_values_for_type(x509.DNSName)


def test_chart_made_set_carries_renewal_and_revision() -> None:
    """The clients restart when the chart makes a new set: their pod
    annotation is the revision stored on the agent Secret."""
    agent = _tls_secrets(_render(_RELEASE))[_AGENT_SECRET]
    annotations = agent["metadata"]["annotations"]
    renew_after = int(annotations["onyx.app/craft-fc-cert-renew-after"])
    cert = _cert(agent, "tls.crt")

    assert renew_after < cert.not_valid_after_utc.timestamp()
    assert annotations["onyx.app/craft-fc-cert-revision"] == "1"
    for template in _CLIENT_TEMPLATES:
        pod = _render(_RELEASE, template)[0]["spec"]["template"]["metadata"]
        assert pod["annotations"]["onyx.app/craft-fc-cert-revision"] == "1"
    existing = _render([*_RELEASE, *_EXISTING], _CLIENT_TEMPLATES[0])[0]
    assert (
        "onyx.app/craft-fc-cert-revision"
        not in (existing["spec"]["template"]["metadata"]["annotations"])
    )


@pytest.fixture
def kube_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeKubeApi]:
    """Renders with --dry-run=server against a fake API, so lookup sees the
    Secrets in `api.secrets`."""
    with fake_kube_api(tmp_path) as api:
        monkeypatch.setenv("KUBECONFIG", str(api.kubeconfig))
        yield api


def _upgrade(
    api: FakeKubeApi, extra: list[str] | None = None
) -> tuple[dict[str, dict[str, Any]], str]:
    """One render against the stored Secrets: (TLS Secrets, client pod revision).
    The rendered Secrets are stored, as an upgrade would."""
    args = [*_RELEASE, *(extra or []), "--dry-run=server"]
    secrets = _tls_secrets(_render(args))
    pod = _render(args, _CLIENT_TEMPLATES[0])[0]["spec"]["template"]["metadata"]
    for secret in secrets.values():
        meta = secret["metadata"]
        api.secrets[(meta["namespace"], meta["name"])] = secret
    return secrets, pod["annotations"]["onyx.app/craft-fc-cert-revision"]


def _data(secrets: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {name: secret["data"] for name, secret in secrets.items()}


def _mark_revision(api: FakeKubeApi, revision: str) -> None:
    """Helm template is always revision 1; an older stored set shows whether
    the clients keep or change their pod annotation."""
    agent = api.secrets[(_AGENT_NS, _AGENT_SECRET)]
    agent["metadata"]["annotations"]["onyx.app/craft-fc-cert-revision"] = revision


def test_upgrade_keeps_the_stored_certificates(kube_api: FakeKubeApi) -> None:
    first, _ = _upgrade(kube_api)
    _mark_revision(kube_api, "7")

    second, revision = _upgrade(kube_api)

    assert _data(second) == _data(first)
    assert revision == "7"


@pytest.mark.parametrize(
    "change",
    ["client_secret_gone", "renewal_due", "new_server_name", "ca_mismatch"],
)
def test_upgrade_makes_a_new_set(kube_api: FakeKubeApi, change: str) -> None:
    first, _ = _upgrade(kube_api)
    _mark_revision(kube_api, "7")
    extra: list[str] = []
    if change == "client_secret_gone":
        del kube_api.secrets[("onyx", _CLIENT_SECRET)]
    elif change == "renewal_due":
        agent = kube_api.secrets[(_AGENT_NS, _AGENT_SECRET)]
        agent["metadata"]["annotations"]["onyx.app/craft-fc-cert-renew-after"] = "1"
    elif change == "new_server_name":
        extra = ["--set-string", "craft.hostAgent.client.tlsServerName=a.example"]
    else:
        client = kube_api.secrets[("onyx", _CLIENT_SECRET)]
        client["data"]["ca.crt"] = base64.b64encode(b"other").decode()

    second, revision = _upgrade(kube_api, extra)

    assert (
        second[_AGENT_SECRET]["data"]["ca.crt"]
        != first[_AGENT_SECRET]["data"]["ca.crt"]
    )
    assert (
        second[_AGENT_SECRET]["data"]["ca.crt"]
        == second[_CLIENT_SECRET]["data"]["ca.crt"]
    )
    # The clients restart: their annotation is the new set's revision.
    assert revision == "1"


@pytest.mark.parametrize(
    ("extra", "allow_http"),
    [
        # The bundled store is plain HTTP inside the cluster.
        (["--set", "minio.enabled=true"], True),
        (["--set", "minio.enabled=false", "--set", "objectStore.enabled=true"], True),
        # External stores: S3 / GCS / Azure, or the bundled store not in use.
        (["--set", "minio.enabled=false", "--set", "objectStore.enabled=false"], False),
        (
            [
                "--set",
                "minio.enabled=true",
                "--set-string",
                "configMap.FILE_STORE_BACKEND=azure",
            ],
            False,
        ),
    ],
)
def test_plain_http_transfers_only_for_the_bundled_store(
    extra: list[str], allow_http: bool
) -> None:
    args = _pod_spec(_render([*_RELEASE, *extra]))["containers"][0]["args"]
    assert ("--transfer-allow-http" in args) is allow_http


_OBJECT_STORE_ONLY = [
    "--set",
    "minio.enabled=false",
    "--set",
    "objectStore.enabled=true",
]
_MINIO_ONLY = ["--set", "minio.enabled=true", "--set", "objectStore.enabled=false"]


@pytest.mark.parametrize(
    ("extra", "endpoint", "legacy"),
    [
        (
            [],
            "http://onyx-object-store.onyx.svc.cluster.local:8333",
            "http://onyx-minio.onyx.svc.cluster.local:9000",
        ),
        (
            _OBJECT_STORE_ONLY,
            "http://onyx-object-store.onyx.svc.cluster.local:8333",
            None,
        ),
        (_MINIO_ONLY, "http://onyx-minio.onyx.svc.cluster.local:9000", None),
        (
            [*_OBJECT_STORE_ONLY, "--set-string", "global.clusterDomain=corp.internal"],
            "http://onyx-object-store.onyx.svc.corp.internal:8333",
            None,
        ),
    ],
)
def test_bundled_store_endpoint_resolves_from_the_agent_namespace(
    extra: list[str], endpoint: str, legacy: str | None
) -> None:
    # The host agent uploads to the presigned URL host from its own namespace.
    data = _configmap_data([*_RELEASE, *extra])
    assert data["S3_ENDPOINT_URL"] == endpoint
    assert data.get("S3_LEGACY_ENDPOINT_URL") == legacy


@pytest.mark.parametrize(
    ("extra", "endpoint"),
    [
        # Pod runtime: the short Service name, as before.
        (_OBJECT_STORE_ONLY, "http://onyx-object-store:8333"),
        (_MINIO_ONLY, "http://onyx-minio:9000"),
    ],
)
def test_bundled_store_endpoint_without_firecracker_is_unchanged(
    extra: list[str], endpoint: str
) -> None:
    assert _configmap_data(extra)["S3_ENDPOINT_URL"] == endpoint


def test_external_store_endpoint_is_unchanged_with_firecracker() -> None:
    data = _configmap_data(
        [
            *_RELEASE,
            "--set",
            "minio.enabled=false",
            "--set",
            "objectStore.enabled=false",
            "--set-string",
            "configMap.S3_ENDPOINT_URL=https://s3.example.internal",
        ]
    )
    assert data["S3_ENDPOINT_URL"] == "https://s3.example.internal"
