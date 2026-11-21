"""Render tests for the relay → sandbox-proxy mTLS hop (craft.hostAgent.relayTls):
the chart makes a relay CA with the proxy and relay certificates, the proxy
gets a separate mTLS port, and customers can bring their own Secrets."""

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
    _by_kind,
    _render,
)
from tests.external_dependency_unit.craft_helm.test_craft_fc_host_agent_release import (
    _RELEASE,
    _cert,
    _dns_names,
    _tls_secrets,
)

_RELAY_TEMPLATE = "templates/craft-fc-relay-tls.yaml"
_AGENT_TEMPLATE = "templates/craft-fc-host-agent.yaml"
_PROXY_TEMPLATE = "templates/sandbox-proxy/deployment.yaml"
_SERVICE_TEMPLATE = "templates/sandbox-proxy/service.yaml"
_PROXY_SECRET = "onyx-sandbox-proxy-relay-tls"
_RELAY_SECRET = "onyx-craft-fc-host-agent-relay-tls"
_PROXY_FQDN = "onyx-sandbox-proxy.onyx.svc.cluster.local"
_RELAY_NAME = f"onyx-craft-fc-relay.{_AGENT_NS}.svc"
_EXISTING = [
    "--set-string",
    "craft.hostAgent.relayTls.existingSecret=my-relay",
    "--set-string",
    "craft.hostAgent.relayTls.proxyExistingSecret=my-proxy",
]


def _proxy_pod(args: list[str]) -> dict[str, Any]:
    return _render(args, _PROXY_TEMPLATE)[0]["spec"]["template"]


def _proxy_env(args: list[str]) -> dict[str, Any]:
    return {
        e["name"]: e.get("value")
        for e in _proxy_pod(args)["spec"]["containers"][0]["env"]
    }


def _agent_container(args: list[str]) -> dict[str, Any]:
    return _by_kind(_render(args, _AGENT_TEMPLATE), "DaemonSet")["spec"]["template"][
        "spec"
    ]["containers"][0]


def _volume_secret(pod_spec: dict[str, Any], name: str) -> str:
    volume = next(v for v in pod_spec["volumes"] if v["name"] == name)
    return volume["secret"]["secretName"]


def test_chart_makes_the_relay_certificates() -> None:
    secrets = _tls_secrets(_render(_RELEASE, _RELAY_TEMPLATE))
    proxy, relay = secrets[_PROXY_SECRET], secrets[_RELAY_SECRET]
    agent_ca = _tls_secrets(_render(_RELEASE, _AGENT_TEMPLATE))[
        "onyx-craft-fc-host-agent-tls"
    ]["data"]["ca.crt"]

    assert proxy["metadata"]["namespace"] == "onyx"
    assert relay["metadata"]["namespace"] == _AGENT_NS
    # Its own CA: an agent or agent-client certificate never opens the port.
    assert proxy["data"]["ca.crt"] == relay["data"]["ca.crt"] != agent_ca
    ca = _cert(proxy, "ca.crt")
    proxy_cert, relay_cert = _cert(proxy, "tls.crt"), _cert(relay, "tls.crt")
    for leaf in (proxy_cert, relay_cert):
        leaf.verify_directly_issued_by(ca)
    assert _dns_names(proxy_cert) == [_PROXY_FQDN, "onyx-sandbox-proxy.onyx.svc"]
    assert _dns_names(relay_cert) == [_RELAY_NAME]
    assert (
        ExtendedKeyUsageOID.CLIENT_AUTH
        in relay_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )


def test_proxy_serves_the_relay_port_and_pins_the_relay() -> None:
    pod = _proxy_pod(_RELEASE)
    container = pod["spec"]["containers"][0]
    env = _proxy_env(_RELEASE)
    service = _render(_RELEASE, _SERVICE_TEMPLATE)[0]

    assert {"name": "relay-tls", "containerPort": 8443, "protocol": "TCP"} in (
        container["ports"]
    )
    assert env["SANDBOX_PROXY_RELAY_TLS_PORT"] == "8443"
    assert env["SANDBOX_PROXY_RELAY_TLS_ALLOWED_SANS"] == _RELAY_NAME
    assert env["SANDBOX_PROXY_RELAY_TLS_CLIENT_CA_PATH"] == (
        "/etc/onyx/sandbox-proxy-relay-tls/ca.crt"
    )
    assert _volume_secret(pod["spec"], "relay-tls") == _PROXY_SECRET
    assert (
        pod["metadata"]["annotations"]["onyx.app/craft-fc-relay-cert-revision"] == "1"
    )
    assert {
        "name": "relay-tls",
        "port": 8443,
        "targetPort": "relay-tls",
        "protocol": "TCP",
    } in (service["spec"]["ports"])


def test_agent_dials_the_relay_port_with_its_certificate() -> None:
    container = _agent_container(_RELEASE)
    pod_spec = _by_kind(_render(_RELEASE, _AGENT_TEMPLATE), "DaemonSet")["spec"][
        "template"
    ]["spec"]
    proxy_cert = _cert(
        _tls_secrets(_render(_RELEASE, _RELAY_TEMPLATE))[_PROXY_SECRET], "tls.crt"
    )

    assert f"--egress-proxy={_PROXY_FQDN}:8443" in container["args"]
    assert (
        "--egress-proxy-tls-cert=/etc/craft-fc/relay-tls/tls.crt" in container["args"]
    )
    assert f"--egress-proxy-tls-server-name={_PROXY_FQDN}" in container["args"]
    assert _PROXY_FQDN in _dns_names(proxy_cert)
    assert _volume_secret(pod_spec, "relay-tls") == _RELAY_SECRET


def test_server_name_is_added_to_the_proxy_certificate() -> None:
    args = [
        *_RELEASE,
        "--set-string",
        "craft.hostAgent.relayTls.serverName=proxy.example",
    ]
    proxy_cert = _cert(
        _tls_secrets(_render(args, _RELAY_TEMPLATE))[_PROXY_SECRET], "tls.crt"
    )

    assert _dns_names(proxy_cert)[0] == "proxy.example"
    assert (
        "--egress-proxy-tls-server-name=proxy.example" in _agent_container(args)["args"]
    )


def test_existing_secrets_are_used_unchanged() -> None:
    args = [*_RELEASE, *_EXISTING]
    pod = _proxy_pod(args)
    agent_spec = _by_kind(_render(args, _AGENT_TEMPLATE), "DaemonSet")["spec"][
        "template"
    ]["spec"]

    assert _render(args, _RELAY_TEMPLATE) == []
    assert _volume_secret(pod["spec"], "relay-tls") == "my-proxy"
    assert _volume_secret(agent_spec, "relay-tls") == "my-relay"
    # Own PKI: no pin unless asked, and no restart annotation.
    assert _proxy_env(args)["SANDBOX_PROXY_RELAY_TLS_ALLOWED_SANS"] == ""
    assert "onyx.app/craft-fc-relay-cert-revision" not in pod["metadata"]["annotations"]
    pinned = [
        *args,
        "--set-string",
        "craft.hostAgent.relayTls.clientAllowedSans=spiffe://example/relay",
    ]
    assert _proxy_env(pinned)["SANDBOX_PROXY_RELAY_TLS_ALLOWED_SANS"] == (
        "spiffe://example/relay"
    )


@pytest.mark.parametrize(
    "secret_value",
    [
        "craft.hostAgent.relayTls.existingSecret=my-relay",
        "craft.hostAgent.relayTls.proxyExistingSecret=my-proxy",
    ],
)
def test_one_existing_secret_alone_fails(secret_value: str) -> None:
    result = render_chart(
        [*_RELEASE, "--set-string", secret_value, "--show-only", _PROXY_TEMPLATE]
    )
    assert result.returncode != 0
    assert "set both craft.hostAgent.relayTls.existingSecret" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        [],  # pod runtime
        [*_RELEASE, "--set", "craft.hostAgent.relayTls.enabled=false"],
    ],
)
def test_no_relay_port_without_relay_tls(args: list[str]) -> None:
    container = _proxy_pod(args)["spec"]["containers"][0]
    service = _render(args, _SERVICE_TEMPLATE)[0]

    assert _render(args, _RELAY_TEMPLATE) == []
    assert not [
        e for e in container["env"] if e["name"].startswith("SANDBOX_PROXY_RELAY_TLS")
    ]
    assert [p["name"] for p in container["ports"]] == ["proxy", "healthz"]
    assert [p["name"] for p in service["spec"]["ports"]] == ["proxy"]


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
    """One render against the stored Secrets: (relay Secrets, proxy pod
    revision). The rendered Secrets are stored, as an upgrade would."""
    args = [*_RELEASE, *(extra or []), "--dry-run=server"]
    secrets = _tls_secrets(_render(args, _RELAY_TEMPLATE))
    revision = _proxy_pod(args)["metadata"]["annotations"][
        "onyx.app/craft-fc-relay-cert-revision"
    ]
    for secret in secrets.values():
        meta = secret["metadata"]
        api.secrets[(meta["namespace"], meta["name"])] = secret
    return secrets, revision


def _mark_revision(api: FakeKubeApi, revision: str) -> None:
    proxy = api.secrets[("onyx", _PROXY_SECRET)]
    proxy["metadata"]["annotations"]["onyx.app/craft-fc-relay-cert-revision"] = revision


def test_upgrade_keeps_the_stored_relay_certificates(kube_api: FakeKubeApi) -> None:
    first, _ = _upgrade(kube_api)
    _mark_revision(kube_api, "7")

    second, revision = _upgrade(kube_api)

    assert {n: s["data"] for n, s in second.items()} == {
        n: s["data"] for n, s in first.items()
    }
    assert revision == "7"


@pytest.mark.parametrize(
    "change", ["relay_secret_gone", "renewal_due", "new_server_name", "ca_mismatch"]
)
def test_upgrade_makes_a_new_relay_set(kube_api: FakeKubeApi, change: str) -> None:
    first, _ = _upgrade(kube_api)
    _mark_revision(kube_api, "7")
    extra: list[str] = []
    if change == "relay_secret_gone":
        del kube_api.secrets[(_AGENT_NS, _RELAY_SECRET)]
    elif change == "renewal_due":
        proxy = kube_api.secrets[("onyx", _PROXY_SECRET)]
        proxy["metadata"]["annotations"]["onyx.app/craft-fc-relay-cert-renew-after"] = (
            "1"
        )
    elif change == "new_server_name":
        extra = ["--set-string", "craft.hostAgent.relayTls.serverName=p.example"]
    else:
        relay = kube_api.secrets[(_AGENT_NS, _RELAY_SECRET)]
        relay["data"]["ca.crt"] = base64.b64encode(b"other").decode()

    second, revision = _upgrade(kube_api, extra)

    new_ca = second[_PROXY_SECRET]["data"]["ca.crt"]
    assert new_ca != first[_PROXY_SECRET]["data"]["ca.crt"]
    assert new_ca == second[_RELAY_SECRET]["data"]["ca.crt"]
    # The proxy restarts: its annotation is the new set's revision.
    assert revision == "1"
