"""Render tests for the Craft Firecracker host agent metrics (ENG-4570).

Metrics are off by default: the agent then renders with no metrics flag,
port or ServiceMonitor. With craft.hostAgent.metrics.enabled the agent serves
/metrics on its own port, the NetworkPolicy opens only that port to scrapers,
and monitoring.serviceMonitors.enabled adds a ServiceMonitor."""

from typing import Any

from tests.external_dependency_unit.craft_helm.test_craft_fc_host_agent import (
    _AGENT_NS,
    _FIRECRACKER,
    _by_kind,
    _render,
)

_SM_TEMPLATE = "templates/craft-fc-host-agent-servicemonitor.yaml"
_METRICS_ON = [*_FIRECRACKER, "--set", "craft.hostAgent.metrics.enabled=true"]
_SM_ON = ["--set", "monitoring.serviceMonitors.enabled=true"]


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
    assert ingress[1] == {"ports": [{"protocol": "TCP", "port": 9555}]}


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
    # The service selects the DaemonSet pods.
    agent_docs = _render([*_METRICS_ON])
    svc_selector = _by_kind(agent_docs, "Service")["spec"]["selector"]
    for key, value in sm["spec"]["selector"]["matchLabels"].items():
        assert svc_selector[key] == value
