"""Render tests for the Craft Firecracker host agent metrics (ENG-4570).

Metrics are off by default: the agent then renders with no metrics flag,
port or ServiceMonitor. With craft.hostAgent.metrics.enabled the agent serves
/metrics on its own port, the NetworkPolicy opens only that port to
Prometheus, and monitoring.serviceMonitors.enabled adds a ServiceMonitor.
/metrics uses the api_server auth rules (auth.metricsAuth,
DISABLE_METRICS_AUTH)."""

from typing import Any

import pytest

from tests.external_dependency_unit.craft_helm.rendering import render_chart
from tests.external_dependency_unit.craft_helm.test_craft_fc_host_agent import (
    _AGENT_NS,
    _FIRECRACKER,
    _by_kind,
    _render,
)

_SM_TEMPLATE = "templates/craft-fc-host-agent-servicemonitor.yaml"
_METRICS_ON = [*_FIRECRACKER, "--set", "craft.hostAgent.metrics.enabled=true"]
_SM_ON = ["--set", "monitoring.serviceMonitors.enabled=true"]
_TEMPLATE = "templates/craft-fc-host-agent.yaml"
_TOKEN_ON = [
    "--set",
    "auth.metricsAuth.enabled=true",
    "--set-string",
    "auth.metricsAuth.values.metrics_auth_token=tok-test",
]
_TOKEN_SECRET = "onyx-craft-fc-host-agent-metrics-auth"
_PROMETHEUS_SOURCE = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "onyx"}},
    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "prometheus"}},
}


def _container(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["containers"][0]


def test_metrics_off_by_default() -> None:
    docs = _render(_FIRECRACKER)
    container = _container(docs)
    assert not [a for a in container["args"] if a.startswith("--metrics-listen")]
    assert [p["name"] for p in container["ports"]] == ["agent"]
    assert [p["name"] for p in _by_kind(docs, "Service")["spec"]["ports"]] == ["agent"]
    assert len(_by_kind(docs, "NetworkPolicy")["spec"]["ingress"]) == 1
    # The ServiceMonitor needs the agent metrics too.
    assert _render([*_FIRECRACKER, *_SM_ON], _SM_TEMPLATE) == []
    assert _render([], _SM_TEMPLATE) == []


def test_metrics_port_flag_service_and_policy() -> None:
    docs = _render(
        [
            *_METRICS_ON,
            "--set",
            "craft.hostAgent.metrics.port=9555",
        ]
    )
    container = _container(docs)
    assert "--metrics-listen=:9555" in container["args"]
    assert {"name": "metrics", "containerPort": 9555, "protocol": "TCP"} in container[
        "ports"
    ]
    assert {
        "name": "metrics",
        "port": 9555,
        "targetPort": "metrics",
        "protocol": "TCP",
    } in _by_kind(docs, "Service")["spec"]["ports"]
    ingress = _by_kind(docs, "NetworkPolicy")["spec"]["ingress"]
    assert len(ingress) == 2
    # The agent API rule is unchanged; the metrics rule opens only 9555.
    assert ingress[0]["ports"] == [{"protocol": "TCP", "port": 7443}]
    # Default source: Prometheus Operator pods in the release namespace.
    assert ingress[1] == {
        "from": [_PROMETHEUS_SOURCE],
        "ports": [{"protocol": "TCP", "port": 9555}],
    }


def test_metrics_policy_sources() -> None:
    docs = _render(
        [
            *_METRICS_ON,
            "--set",
            "craft.hostAgent.metrics.networkPolicyFrom[0].namespaceSelector.matchLabels.name=monitoring",
        ]
    )
    rule = _by_kind(docs, "NetworkPolicy")["spec"]["ingress"][1]
    assert rule["from"] == [
        {"namespaceSelector": {"matchLabels": {"name": "monitoring"}}}
    ]


def test_service_monitor() -> None:
    assert _render(_METRICS_ON, _SM_TEMPLATE) == []
    docs = _render(
        [
            *_METRICS_ON,
            *_SM_ON,
            "--set",
            "monitoring.serviceMonitors.labels.release=onyx-monitoring",
        ],
        _SM_TEMPLATE,
    )
    sm = _by_kind(docs, "ServiceMonitor")
    assert sm["metadata"]["namespace"] == _AGENT_NS
    assert sm["metadata"]["labels"]["release"] == "onyx-monitoring"
    assert sm["spec"]["namespaceSelector"] == {"matchNames": [_AGENT_NS]}
    assert (
        sm["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"]
        == "craft-fc-host-agent"
    )
    endpoint = sm["spec"]["endpoints"][0]
    assert endpoint["port"] == "metrics"
    assert endpoint["path"] == "/metrics"
    assert "authorization" not in endpoint
    # The service selects the DaemonSet pods.
    agent_docs = _render([*_METRICS_ON])
    svc_selector = _by_kind(agent_docs, "Service")["spec"]["selector"]
    for key, value in sm["spec"]["selector"]["matchLabels"].items():
        assert svc_selector[key] == value


def _secrets(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["metadata"]["name"]: d for d in docs if d["kind"] == "Secret"}


def test_metrics_locked_without_token() -> None:
    """Like the api_server: no token and no opt-out = every scrape gets 401."""
    docs = _render(_METRICS_ON)
    args = _container(docs)["args"]
    assert not [a for a in args if a.startswith("--metrics-token-file")]
    assert "--metrics-auth-disabled" not in args
    assert _TOKEN_SECRET not in _secrets(docs)


def test_metrics_auth_disabled() -> None:
    docs = _render(
        [
            *_METRICS_ON,
            *_TOKEN_ON,
            "--set-string",
            "configMap.DISABLE_METRICS_AUTH=true",
        ]
    )
    args = _container(docs)["args"]
    assert "--metrics-auth-disabled" in args
    assert not [a for a in args if a.startswith("--metrics-token-file")]
    assert _TOKEN_SECRET not in _secrets(docs)
    sm = _by_kind(
        _render(
            [
                *_METRICS_ON,
                *_TOKEN_ON,
                *_SM_ON,
                "--set-string",
                "configMap.DISABLE_METRICS_AUTH=true",
            ],
            _SM_TEMPLATE,
        ),
        "ServiceMonitor",
    )
    assert "authorization" not in sm["spec"]["endpoints"][0]


def test_metrics_token_copied_and_mounted() -> None:
    docs = _render([*_METRICS_ON, *_TOKEN_ON])
    secret = _secrets(docs)[_TOKEN_SECRET]
    assert secret["metadata"]["namespace"] == _AGENT_NS
    assert secret["stringData"] == {"metrics_auth_token": "tok-test"}
    container = _container(docs)
    assert (
        "--metrics-token-file=/etc/craft-fc/metrics-auth/metrics_auth_token"
        in container["args"]
    )
    # No subPath, so the kubelet updates the file when the Secret rotates.
    assert {
        "name": "metrics-auth",
        "mountPath": "/etc/craft-fc/metrics-auth",
        "readOnly": True,
    } in container["volumeMounts"]
    volumes = _by_kind(docs, "DaemonSet")["spec"]["template"]["spec"]["volumes"]
    assert {
        "name": "metrics-auth",
        "secret": {"secretName": _TOKEN_SECRET, "defaultMode": 0o400},
    } in volumes

    sm = _by_kind(
        _render([*_METRICS_ON, *_TOKEN_ON, *_SM_ON], _SM_TEMPLATE), "ServiceMonitor"
    )
    assert sm["spec"]["endpoints"][0]["authorization"] == {
        "credentials": {"name": _TOKEN_SECRET, "key": "metrics_auth_token"}
    }


def test_metrics_token_existing_secret() -> None:
    extra = [
        *_METRICS_ON,
        "--set",
        "auth.metricsAuth.enabled=true",
        "--set-string",
        "auth.metricsAuth.existingSecret=onyx-app-secrets",
        "--set-string",
        "auth.metricsAuth.secretKeys.METRICS_AUTH_TOKEN=METRICS_AUTH_TOKEN",
        "--set-string",
        "craft.hostAgent.metrics.authExistingSecret=agent-metrics",
    ]
    docs = _render(extra)
    assert "agent-metrics" not in _secrets(docs)
    assert _TOKEN_SECRET not in _secrets(docs)
    assert (
        "--metrics-token-file=/etc/craft-fc/metrics-auth/METRICS_AUTH_TOKEN"
        in _container(docs)["args"]
    )
    sm = _by_kind(_render([*extra, *_SM_ON], _SM_TEMPLATE), "ServiceMonitor")
    assert sm["spec"]["endpoints"][0]["authorization"] == {
        "credentials": {"name": "agent-metrics", "key": "METRICS_AUTH_TOKEN"}
    }


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--set-string", "auth.metricsAuth.existingSecret=onyx-app-secrets"],
        ["--set-string", "auth.metricsAuth.values.metrics_auth_token="],
    ],
)
def test_metrics_token_needs_agent_secret(extra_args: list[str]) -> None:
    result = render_chart(
        [*_METRICS_ON, *_TOKEN_ON, *extra_args, "--show-only", _TEMPLATE]
    )
    assert result.returncode != 0
    assert "craft.hostAgent.metrics.authExistingSecret" in result.stderr
