from __future__ import annotations

import json
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

GRAFANA_API_URL = "https://grafana.com/api/dashboards/{dashboard_id}/revisions/latest/download"
DATASOURCE_NAME = "VictoriaMetrics"
DATASOURCE_UID = "victoriametrics"
DATASOURCE_REF = {"type": "prometheus", "uid": DATASOURCE_UID}
DATASOURCE_PLACEHOLDERS = {
    "${DS_PROM}",
    "${DS_PROMETHEUS}",
    "${ds_prometheus}",
}

DASHBOARD_SOURCES = {
    "Community/postgresql-database.json": 9628,
    "Community/redis-dashboard.json": 763,
    "Community/celery-tasks-dashboard.json": 20076,
    "Community/node-exporter-full.json": 1860,
}


def fetch_community_dashboard(dashboard_id: int) -> dict[str, Any]:
    with urllib.request.urlopen(
        GRAFANA_API_URL.format(dashboard_id=dashboard_id), timeout=30
    ) as response:
        return json.load(response)


def normalize_datasource(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, str):
        if value in DATASOURCE_PLACEHOLDERS or value.lower() == "prometheus":
            return deepcopy(DATASOURCE_REF)
        return value

    if isinstance(value, dict):
        normalized = {
            key: normalize_datasource(subvalue) for key, subvalue in value.items()
        }
        uid = normalized.get("uid")
        if isinstance(uid, str) and (uid in DATASOURCE_PLACEHOLDERS or uid.startswith("${")):
            normalized["uid"] = DATASOURCE_UID
        if normalized.get("type") == "prometheus":
            normalized.setdefault("uid", DATASOURCE_UID)
        return normalized

    return value


def normalize_dashboard(obj: Any) -> Any:
    if isinstance(obj, dict):
        normalized: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "__inputs":
                continue
            if key == "id":
                normalized[key] = None
                continue
            if key == "datasource":
                normalized[key] = normalize_datasource(value)
                continue

            normalized[key] = normalize_dashboard(value)

        if normalized.get("type") == "datasource":
            normalized["current"] = {
                "selected": True,
                "text": DATASOURCE_NAME,
                "value": DATASOURCE_UID,
            }
            normalized["options"] = [
                {
                    "selected": True,
                    "text": DATASOURCE_NAME,
                    "value": DATASOURCE_UID,
                }
            ]
            normalized["query"] = "prometheus"
            normalized["regex"] = ""

        if normalized.get("type") == "prometheus" and "uid" not in normalized:
            normalized["uid"] = DATASOURCE_UID

        return normalized

    if isinstance(obj, list):
        return [normalize_dashboard(item) for item in obj]

    if isinstance(obj, str) and obj in DATASOURCE_PLACEHOLDERS:
        return DATASOURCE_UID

    return obj


def make_annotation_list() -> dict[str, Any]:
    return {
        "list": [
            {
                "builtIn": 1,
                "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard",
            }
        ]
    }


def make_timeseries_panel(
    *,
    panel_id: int,
    title: str,
    expr: str,
    grid_pos: dict[str, int],
    legend_format: str = "__auto",
    unit: str | None = None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {"color": {"mode": "palette-classic"}}
    if unit:
        defaults["unit"] = unit

    return {
        "datasource": deepcopy(DATASOURCE_REF),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "legend": {
                "calcs": ["lastNotNull", "max"],
                "displayMode": "table",
                "placement": "bottom",
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "targets": [
            {
                "datasource": deepcopy(DATASOURCE_REF),
                "editorMode": "code",
                "expr": expr,
                "legendFormat": legend_format,
                "range": True,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "timeseries",
    }


def make_stat_panel(
    *,
    panel_id: int,
    title: str,
    expr: str,
    grid_pos: dict[str, int],
    unit: str | None = None,
    thresholds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "color": {"mode": "thresholds"},
        "mappings": [],
        "thresholds": {
            "mode": "absolute",
            "steps": thresholds
            or [
                {"color": "green", "value": None},
                {"color": "red", "value": 1},
            ],
        },
    }
    if unit:
        defaults["unit"] = unit

    return {
        "datasource": deepcopy(DATASOURCE_REF),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
        "targets": [
            {
                "datasource": deepcopy(DATASOURCE_REF),
                "editorMode": "code",
                "expr": expr,
                "legendFormat": "__auto",
                "range": True,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "stat",
    }


def make_bargauge_panel(
    *,
    panel_id: int,
    title: str,
    expr: str,
    grid_pos: dict[str, int],
    unit: str | None = None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "color": {"mode": "palette-classic"},
        "mappings": [],
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}],
        },
    }
    if unit:
        defaults["unit"] = unit

    return {
        "datasource": deepcopy(DATASOURCE_REF),
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": grid_pos,
        "id": panel_id,
        "options": {
            "displayMode": "basic",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showUnfilled": True,
        },
        "targets": [
            {
                "datasource": deepcopy(DATASOURCE_REF),
                "editorMode": "code",
                "expr": expr,
                "legendFormat": "{{tenant_id}}{{handler}}",
                "range": True,
                "refId": "A",
            }
        ],
        "title": title,
        "type": "bargauge",
    }


def build_activa_api_dashboard() -> dict[str, Any]:
    excluded_handlers = '{handler!~"/health|/metrics|/openapi.json"}'

    return {
        "annotations": make_annotation_list(),
        "editable": False,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": [
            make_timeseries_panel(
                panel_id=1,
                title="Request Rate by Handler",
                expr=(
                    "sum by (handler) "
                    f"(rate(http_requests_total{excluded_handlers}[5m]))"
                ),
                legend_format="{{handler}}",
                unit="reqps",
                grid_pos={"h": 9, "w": 12, "x": 0, "y": 0},
            ),
            make_timeseries_panel(
                panel_id=2,
                title="P95 Latency by Handler",
                expr=(
                    "histogram_quantile(0.95, "
                    "sum by (le, handler) "
                    f"(rate(http_request_duration_seconds_bucket{excluded_handlers}[5m])))"
                ),
                legend_format="{{handler}}",
                unit="s",
                grid_pos={"h": 9, "w": 12, "x": 12, "y": 0},
            ),
            make_stat_panel(
                panel_id=3,
                title="5xx Error Rate",
                expr=(
                    'sum(rate(http_requests_total{handler!~"/health|/metrics|/openapi.json",status=~"5.."}[5m])) '
                    '/ clamp_min('
                    'sum(rate(http_requests_total{handler!~"/health|/metrics|/openapi.json"}[5m])), 0.001)'
                ),
                unit="percentunit",
                thresholds=[
                    {"color": "green", "value": None},
                    {"color": "orange", "value": 0.02},
                    {"color": "red", "value": 0.05},
                ],
                grid_pos={"h": 7, "w": 6, "x": 0, "y": 9},
            ),
            make_stat_panel(
                panel_id=4,
                title="In-Flight Requests",
                expr=(
                    "sum(http_requests_inprogress"
                    '{handler!~"/health|/metrics|/openapi.json"})'
                ),
                grid_pos={"h": 7, "w": 6, "x": 6, "y": 9},
            ),
            make_stat_panel(
                panel_id=5,
                title="DB Pool Utilization",
                expr="sum(onyx_db_pool_checked_out) / clamp_min(sum(onyx_db_pool_size), 1)",
                unit="percentunit",
                thresholds=[
                    {"color": "green", "value": None},
                    {"color": "orange", "value": 0.7},
                    {"color": "red", "value": 0.9},
                ],
                grid_pos={"h": 7, "w": 6, "x": 12, "y": 9},
            ),
            make_stat_panel(
                panel_id=6,
                title="DB Checkout Timeouts / 5m",
                expr="sum(increase(onyx_db_pool_checkout_timeout_total[5m]))",
                grid_pos={"h": 7, "w": 6, "x": 18, "y": 9},
            ),
            make_timeseries_panel(
                panel_id=7,
                title="Slow Requests by Handler",
                expr=(
                    "sum by (handler) "
                    f"(rate(onyx_api_slow_requests_total{excluded_handlers}[5m]))"
                ),
                legend_format="{{handler}}",
                unit="reqps",
                grid_pos={"h": 9, "w": 12, "x": 0, "y": 16},
            ),
            make_bargauge_panel(
                panel_id=8,
                title="Top Tenants by Request Rate",
                expr="topk(10, sum by (tenant_id) (rate(onyx_api_requests_by_tenant_total[5m])))",
                unit="reqps",
                grid_pos={"h": 9, "w": 12, "x": 12, "y": 16},
            ),
        ],
        "refresh": "30s",
        "schemaVersion": 39,
        "style": "dark",
        "tags": ["activa", "api", "fastapi", "prometheus"],
        "templating": {"list": []},
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "title": "ACTIVA API Overview",
        "uid": "activa-api-overview",
        "version": 1,
        "weekStart": "",
    }


def write_dashboard(path: Path, dashboard: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboards_dir = repo_root / "dashboards"

    for relative_path, dashboard_id in DASHBOARD_SOURCES.items():
        dashboard = normalize_dashboard(fetch_community_dashboard(dashboard_id))
        write_dashboard(dashboards_dir / relative_path, dashboard)
        print(f"Wrote {relative_path} from dashboard ID {dashboard_id}")

    write_dashboard(
        dashboards_dir / "ACTIVA/activa-api-overview.json",
        build_activa_api_dashboard(),
    )
    print("Wrote ACTIVA/activa-api-overview.json")


if __name__ == "__main__":
    main()
