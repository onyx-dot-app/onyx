"""Render tests for the Craft Firecracker host agent alert rules and dashboard.

Both are off by default. The PrometheusRule needs
monitoring.prometheusRules.enabled and the agent metrics; the dashboard
ConfigMap needs monitoring.grafana.dashboards.enabled and the agent metrics.
Every craft_fc_host_agent_* name in them must be a metric of the agent."""

import json
import re
from typing import Any

from tests.common.paths import find_ancestor_containing
from tests.external_dependency_unit.craft_helm.test_craft_fc_host_agent import (
    _AGENT_NS,
    _FIRECRACKER,
    _render,
)

_RULE_TEMPLATE = "templates/craft-fc-host-agent-prometheusrule.yaml"
_DASHBOARD_TEMPLATE = "templates/grafana-dashboards.yaml"
_METRICS_ON = [*_FIRECRACKER, "--set", "craft.hostAgent.metrics.enabled=true"]
_RULES_ON = ["--set", "monitoring.prometheusRules.enabled=true"]
_DASHBOARDS_ON = ["--set", "monitoring.grafana.dashboards.enabled=true"]
_JOB = "onyx-craft-fc-host-agent"
_DASHBOARD_KEY = "onyx-craft-fc-host-agent.json"
_REPO_ROOT = find_ancestor_containing("microvm/internal/metrics")
_ALERTS = [
    "CraftFcHostAgentDown",
    "CraftFcHostAgentPodsMissing",
    "CraftFcCreateFailures",
    "CraftFcAdmissionRefusals",
    "CraftFcSessionTransferFailures",
    "CraftFcRelayErrors",
    "CraftFcNodeMemoryLow",
    "CraftFcTemplateUnusable",
]


def _rules(extra_args: list[str]) -> list[dict[str, Any]]:
    docs = _render(extra_args, _RULE_TEMPLATE)
    if not docs:
        return []
    assert len(docs) == 1
    return docs[0]["spec"]["groups"][0]["rules"]


def _by_alert(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["alert"]: r for r in rules}


def _agent_metric_names() -> set[str]:
    src = (_REPO_ROOT / "microvm/internal/metrics/metrics.go").read_text()
    return {
        f"craft_fc_host_agent_{n}"
        for n in re.findall(r'(?:Name: |d\()"([a-z_]+)"', src)
    }


def _used_metric_names(text: str) -> set[str]:
    names = re.findall(r"craft_fc_host_agent_[a-z_]+", text)
    return {re.sub(r"_(bucket|count|sum)$", "", n) for n in names}


def _dashboard(extra_args: list[str]) -> dict[str, Any] | None:
    for doc in _render(extra_args, _DASHBOARD_TEMPLATE):
        if _DASHBOARD_KEY in doc.get("data", {}):
            return json.loads(doc["data"][_DASHBOARD_KEY])
    return None


def test_rules_off_by_default() -> None:
    assert _rules(_METRICS_ON) == []
    # The rules need the agent metrics and the Firecracker runtime.
    assert _rules([*_FIRECRACKER, *_RULES_ON]) == []
    assert _rules(_RULES_ON) == []


def test_rules_render_with_selectors_labels_and_runbooks() -> None:
    docs = _render(
        [
            *_METRICS_ON,
            *_RULES_ON,
            "--set",
            "monitoring.prometheusRules.labels.release=onyx-monitoring",
            "--set",
            "craft.hostAgent.alerts.extraLabels.team=craft",
        ],
        _RULE_TEMPLATE,
    )
    assert docs[0]["kind"] == "PrometheusRule"
    assert docs[0]["metadata"]["labels"]["release"] == "onyx-monitoring"
    rules = docs[0]["spec"]["groups"][0]["rules"]
    assert [r["alert"] for r in rules] == _ALERTS
    # Prometheus templates must reach the rule unrendered by Helm.
    assert "{{ $labels.node }}" in rules[0]["annotations"]["summary"]
    for rule in rules:
        assert rule["labels"]["team"] == "craft"
        assert rule["labels"]["severity"] in {"warning", "critical"}
        anchor = rule["alert"].lower()
        assert rule["annotations"]["runbook_url"].endswith(f"RUNBOOKS.md#{anchor}")
        expr = rule["expr"]
        if rule["alert"] == "CraftFcHostAgentPodsMissing":
            assert f'daemonset="{_JOB}", namespace="{_AGENT_NS}"' in expr
        else:
            assert f'job="{_JOB}", namespace="{_AGENT_NS}"' in expr


def test_runbook_has_a_section_per_alert() -> None:
    runbook = (_REPO_ROOT / "microvm/RUNBOOKS.md").read_text()
    headings = set(re.findall(r"^### (\w+)$", runbook, re.MULTILINE))
    assert set(_ALERTS) <= headings


def test_rules_follow_namespace_and_thresholds() -> None:
    rules = _by_alert(
        _rules(
            [
                *_METRICS_ON,
                *_RULES_ON,
                "--set",
                "craft.hostAgent.namespace=fc-agents",
                "--set",
                "craft.hostAgent.alerts.memoryAvailableRatio=0.25",
                "--set",
                "craft.hostAgent.alerts.admissionRefusals=40",
                "--set-string",
                "craft.hostAgent.alerts.runbookUrl=https://wiki.example/fc",
            ]
        )
    )
    memory = rules["CraftFcNodeMemoryLow"]
    assert 'namespace="fc-agents"' in memory["expr"]
    assert memory["expr"].rstrip().endswith("< 0.25")
    assert rules["CraftFcAdmissionRefusals"]["expr"].rstrip().endswith(">= 40")
    assert (
        memory["annotations"]["runbook_url"]
        == "https://wiki.example/fc#craftfcnodememorylow"
    )


def test_rules_keep_zero_thresholds() -> None:
    rules = _by_alert(
        _rules(
            [
                *_METRICS_ON,
                *_RULES_ON,
                "--set",
                "craft.hostAgent.alerts.createFailureRatio=0",
                "--set",
                "craft.hostAgent.alerts.relayErrorRatio=0",
            ]
        )
    )
    assert ") > 0\n" in rules["CraftFcCreateFailures"]["expr"]
    assert ") > 0\n" in rules["CraftFcRelayErrors"]["expr"]


def test_relay_ratio_counts_each_connection_once() -> None:
    expr = _by_alert(_rules([*_METRICS_ON, *_RULES_ON]))["CraftFcRelayErrors"]["expr"]
    # An accepted connection whose proxy dial fails is also upstream_failed.
    denominator = expr.split("/ sum by", 1)[1].split("\n", 1)[0]
    assert 'result=~"accepted|over_cap"' in denominator


def test_rules_use_only_agent_metrics() -> None:
    rules = _rules([*_METRICS_ON, *_RULES_ON])
    used = _used_metric_names(" ".join(r["expr"] for r in rules))
    assert used
    assert used <= _agent_metric_names()


def test_dashboard_needs_firecracker_metrics() -> None:
    assert _dashboard(_DASHBOARDS_ON) is None
    assert _dashboard([*_FIRECRACKER, *_DASHBOARDS_ON]) is None
    assert _dashboard(_METRICS_ON) is None


def test_dashboard_renders_and_uses_only_agent_metrics() -> None:
    dashboard = _dashboard([*_METRICS_ON, *_DASHBOARDS_ON])
    assert dashboard is not None
    assert dashboard["uid"] == "onyx-craft-fc-host-agent"
    variables = {v["name"] for v in dashboard["templating"]["list"]}
    assert {"DS_PROMETHEUS", "namespace", "node"} <= variables
    exprs = [t["expr"] for p in dashboard["panels"] for t in p.get("targets", [])]
    assert exprs
    used = _used_metric_names(" ".join(exprs))
    assert used <= _agent_metric_names()
    # Every agent query is per node.
    for expr in exprs:
        if "craft_fc_host_agent_" in expr:
            assert 'node=~"$node"' in expr
    ids = [p["id"] for p in dashboard["panels"]]
    assert len(ids) == len(set(ids))


def test_dashboard_job_is_the_agent_service_name() -> None:
    # A long name is truncated with a hash, so no suffix match works.
    long_name = "x" * 60
    dashboard = _dashboard(
        [*_METRICS_ON, *_DASHBOARDS_ON, "--set-string", f"fullnameOverride={long_name}"]
    )
    assert dashboard is not None
    text = json.dumps(dashboard)
    assert "__CRAFT_FC_HOST_AGENT_JOB__" not in text
    jobs = set(re.findall(r'job=\\"([^\\"]+)\\"', text))
    assert len(jobs) == 1
    (job,) = jobs
    assert job.startswith("x" * 50) and len(job) == 63
    rules = _rules(
        [*_METRICS_ON, *_RULES_ON, "--set-string", f"fullnameOverride={long_name}"]
    )
    assert f'job="{job}"' in rules[0]["expr"]
