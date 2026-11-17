"""Render tests for the Craft Firecracker host agent alert rules and dashboard.

Both are off by default. The PrometheusRule needs
monitoring.prometheusRules.enabled and the agent metrics; the dashboard
ConfigMap needs monitoring.grafana.dashboards.enabled and the agent metrics.
Every craft_fc_host_agent_* name in them must be a metric of the agent."""

import json
import re
from typing import Any

from tests.common.paths import find_ancestor_containing
from tests.external_dependency_unit.craft_helm.rendering import render_chart
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
_DOCS_RUNBOOK = (
    "https://docs.onyx.app/deployment/kubernetes/craft-firecracker-operations"
)
_ALERTS = [
    "CraftFcHostAgentDown",
    "CraftFcHostAgentPodsMissing",
    "CraftFcNodeReportsStale",
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
        assert rule["annotations"]["runbook_url"] == f"{_DOCS_RUNBOOK}#{anchor}"
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


def test_template_unusable_sees_a_failed_root_drive_build() -> None:
    # A failed start-up build refuses no Create (placement skips the node),
    # so only template_ready shows it.
    expr = _by_alert(_rules([*_METRICS_ON, *_RULES_ON]))["CraftFcTemplateUnusable"][
        "expr"
    ]
    assert (
        f'max by (namespace, node) (craft_fc_host_agent_template_ready{{job="{_JOB}", '
        f'namespace="{_AGENT_NS}"}}) == 0'
    ) in expr


def test_node_reports_stale_sees_rejected_reports() -> None:
    # The agent answers scrapes, so only the report timestamp shows that the
    # api_server rejects its reports.
    selector = f'job="{_JOB}", namespace="{_AGENT_NS}"'
    stale = _by_alert(_rules([*_METRICS_ON, *_RULES_ON]))["CraftFcNodeReportsStale"]
    assert " ".join(stale["expr"].split()) == (
        "time() - max by (namespace, node) "
        f"(craft_fc_host_agent_node_report_last_success_timestamp_seconds{{{selector}}}) "
        "> 300"
    )
    assert stale["for"] == "5m"
    assert stale["labels"]["severity"] == "critical"
    custom = _by_alert(
        _rules(
            [
                *_METRICS_ON,
                *_RULES_ON,
                "--set",
                "craft.hostAgent.alerts.nodeReportStaleSeconds=600",
            ]
        )
    )
    assert custom["CraftFcNodeReportsStale"]["expr"].rstrip().endswith("> 600")


def test_relay_ratio_counts_each_connection_once() -> None:
    expr = _by_alert(_rules([*_METRICS_ON, *_RULES_ON]))["CraftFcRelayErrors"]["expr"]
    # An accepted connection whose proxy dial fails is also upstream_failed.
    denominator = expr.split("/ sum by", 1)[1].split("\n", 1)[0]
    assert 'result=~"accepted|over_cap"' in denominator


def test_rules_count_the_first_event_of_a_new_series() -> None:
    # A labeled counter series starts at 1, and increase() does not count
    # that event: every increase() also takes the series that are new.
    for rule in _rules([*_METRICS_ON, *_RULES_ON]):
        expr = rule["expr"]
        assert expr.count("increase(") == expr.count(" unless "), rule["alert"]


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


def test_dashboard_names_every_create_result() -> None:
    src = (_REPO_ROOT / "microvm/internal/metrics/metrics.go").read_text()
    results = set(
        re.findall(r'^\s+Create[A-Z][a-z]+\s+= "([a-z]+)"', src, re.MULTILINE)
    )
    assert "canceled" in results
    dashboard = _dashboard([*_METRICS_ON, *_DASHBOARDS_ON])
    assert dashboard is not None
    (panel,) = [p for p in dashboard["panels"] if p.get("title") == "Create results"]
    for result in results:
        assert f"{result}:" in panel["description"], result
    colored = {o["matcher"]["options"] for o in panel["fieldConfig"]["overrides"]}
    assert {"/ failed$/", "/ canceled$/"} <= colored


def test_dashboard_job_is_the_agent_service_name() -> None:
    # A long name is truncated with a hash, so no suffix match works.
    long_name = "x" * 60
    dashboard = _dashboard(
        [*_METRICS_ON, *_DASHBOARDS_ON, "--set-string", f"fullnameOverride={long_name}"]
    )
    assert dashboard is not None
    text = json.dumps(dashboard)
    assert "__CRAFT_FC_HOST_AGENT_" not in text
    jobs = set(re.findall(r'job=\\"([^\\"]+)\\"', text))
    assert len(jobs) == 1
    (job,) = jobs
    assert job.startswith("x" * 50) and len(job) == 63
    rules = _rules(
        [*_METRICS_ON, *_RULES_ON, "--set-string", f"fullnameOverride={long_name}"]
    )
    assert f'job="{job}"' in rules[0]["expr"]
    assert f'daemonset=\\"{job}\\"' in text


def test_metrics_job_overrides_rules_and_dashboard() -> None:
    custom = ["--set-string", "craft.hostAgent.metrics.job=my-scrape"]
    rules = _by_alert(_rules([*_METRICS_ON, *_RULES_ON, *custom]))
    assert 'job="my-scrape"' in rules["CraftFcHostAgentDown"]["expr"]
    # kube-state-metrics names the DaemonSet, not the scrape job.
    assert f'daemonset="{_JOB}"' in rules["CraftFcHostAgentPodsMissing"]["expr"]
    dashboard = _dashboard([*_METRICS_ON, *_DASHBOARDS_ON, *custom])
    assert dashboard is not None
    text = json.dumps(dashboard)
    assert set(re.findall(r'job=\\"([^\\"]+)\\"', text)) == {"my-scrape"}
    assert f'daemonset=\\"{_JOB}\\"' in text


def test_metrics_job_refuses_quotes() -> None:
    result = render_chart(
        [
            *_METRICS_ON,
            *_RULES_ON,
            *_DASHBOARDS_ON,
            "--set-string",
            'craft.hostAgent.metrics.job=a"b',
        ]
    )
    assert result.returncode != 0
    assert "craft.hostAgent.metrics.job may only have" in result.stderr
