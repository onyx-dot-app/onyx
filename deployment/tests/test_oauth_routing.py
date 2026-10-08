import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("api_host", ["web.example.com", "api.example.com"])
def test_rendered_mcp_routes_match_the_web_domain_resource(
    tmp_path: Path, api_host: str
) -> None:
    chart: Path = REPO_ROOT / "deployment/helm/charts/onyx"
    templates: Path = tmp_path / "templates"
    templates.mkdir()
    (tmp_path / "Chart.yaml").write_text("apiVersion: v2\nname: onyx\nversion: 0.9.4\n")
    shutil.copyfile(chart / "values.yaml", tmp_path / "values.yaml")
    for name in (
        "_helpers.tpl",
        "ingress-api.yaml",
        "ingress-mcp.yaml",
        "ingress-mcp-oauth-callback.yaml",
    ):
        shutil.copyfile(chart / "templates" / name, templates / name)
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [
            "helm",
            "template",
            "onyx",
            str(tmp_path),
            "--set",
            "ingress.enabled=true",
            "--set",
            "mcpServer.enabled=true",
            "--set",
            "ingress.webserver.host=web.example.com",
            "--set",
            f"ingress.api.host={api_host}",
            "--set",
            "configMap.WEB_DOMAIN=https://web.example.com",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    ingresses: dict[str, Any] = {
        document["metadata"]["name"]: document
        for document in yaml.safe_load_all(result.stdout)
        if document is not None
    }
    metadata: dict[str, Any] = ingresses["onyx-ingress-mcp-resource-metadata"]
    rule: dict[str, Any] = metadata["spec"]["rules"][0]
    assert rule["host"] == "web.example.com"
    assert (
        rule["http"]["paths"][0]["backend"]["service"]["name"]
        == "onyx-mcp-server-service"
    )
    assert metadata["spec"]["tls"][0]["hosts"] == ["web.example.com"]
    assert metadata["spec"]["tls"][0]["secretName"] == "onyx-ingress-webserver-tls"
    mcp: dict[str, Any] = ingresses["onyx-ingress-mcp"]
    hosts: list[str] = [rule["host"] for rule in mcp["spec"]["rules"]]
    assert set(hosts) == {"web.example.com", api_host}
    assert len(hosts) == len(set(hosts))
    for rule in mcp["spec"]["rules"]:
        assert (
            rule["http"]["paths"][0]["backend"]["service"]["name"]
            == "onyx-mcp-server-service"
        )

    callback: dict[str, Any] = ingresses["onyx-ingress-mcp-oauth-callback"]
    assert {rule["host"] for rule in callback["spec"]["rules"]} == set(hosts)
    for rule in callback["spec"]["rules"]:
        path: dict[str, Any] = rule["http"]["paths"][0]
        assert path["path"] == "/mcp/oauth/callback"
        assert path["pathType"] == "Exact"
        assert path["backend"]["service"]["name"] == "onyx-webserver"

    api: dict[str, Any] = ingresses["onyx-ingress-api"]
    web_api: dict[str, Any] = next(
        rule for rule in api["spec"]["rules"] if rule["host"] == "web.example.com"
    )
    path = web_api["http"]["paths"][0]
    assert path["backend"]["service"]["name"] == "onyx-api-service"
    assert (
        api["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"]
        == "/$2"
    )
    for endpoint in ("register", "authorize", "token", "revoke", "consent", "grants"):
        match: re.Match[str] | None = re.fullmatch(
            path["path"], f"/api/oauth-provider/{endpoint}"
        )
        assert match is not None
        assert "/" + match.group(2) == f"/oauth-provider/{endpoint}"
    if api_host != "web.example.com":
        assert re.fullmatch(path["path"], "/api/oauth-provider-unrelated/token") is None
    assert any("web.example.com" in tls["hosts"] for tls in api["spec"]["tls"])


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_mcp_oauth_discovery_routes_use_generic_oauth_provider() -> None:
    nginx = _read("deployment/data/nginx/mcp.conf.inc.template")
    helm_nginx = _read("deployment/helm/charts/onyx/templates/nginx-conf.yaml")
    ingress = _read("deployment/helm/charts/onyx/templates/ingress-api.yaml")

    for content in (nginx, helm_nginx, ingress):
        assert "/oauth-provider/metadata" in content
        assert "/mcp-oauth/metadata" not in content

    assert r"^/\.well-known/oauth-authorization-server(/.*)?$" in nginx
    assert r"path: /\.well-known/oauth-authorization-server(/|$)(.*)" in ingress
    assert ingress.count("pathType: ImplementationSpecific") == 3
    assert ingress.count('nginx.ingress.kubernetes.io/use-regex: "true"') == 2
    assert "proxy_pass http://mcp_server;" in nginx


def test_deployment_restarts_nginx() -> None:
    values = _read("deployment/helm/charts/onyx/values.yaml")

    chart_version = re.search(
        r"^version: (\d+)\.(\d+)\.(\d+)$",
        _read("deployment/helm/charts/onyx/Chart.yaml"),
        re.MULTILINE,
    )
    assert chart_version is not None
    assert tuple(int(part) for part in chart_version.groups()) >= (0, 9, 4)
    restart_version = re.search(r'onyx.app/nginx-config-version: "(\d+)"', values)
    assert restart_version is not None
    assert int(restart_version.group(1)) >= 8


def test_ingress_discovery_patterns_match_only_literal_well_known_paths() -> None:
    template = _read("deployment/helm/charts/onyx/templates/ingress-api.yaml") + _read(
        "deployment/helm/charts/onyx/templates/ingress-mcp.yaml"
    )
    paths = re.findall(r"- path: (.+well-known.+)", template)
    assert len(paths) == 2
    for path in paths:
        pattern = re.compile("^" + path)
        literal = path.removesuffix("(/|$)(.*)").replace(r"\.", ".")
        assert pattern.fullmatch(literal)
        assert pattern.fullmatch(literal + "/api/oauth-provider")
        assert pattern.fullmatch(literal + "/mcp")
        assert not pattern.match(literal.replace("/.well-known", "/xwell-known"))
        assert not pattern.match(literal + "-unrelated")
