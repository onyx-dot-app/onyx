import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text()


def test_mcp_oauth_discovery_routes_use_generic_oauth_provider() -> None:
    nginx = _read("deployment/data/nginx/mcp.conf.inc.template")
    helm_nginx = _read("deployment/helm/charts/onyx/templates/nginx-conf.yaml")
    next_config = _read("web/next.config.js")
    ingress = _read(
        "deployment/helm/charts/onyx/templates/ingress-mcp-oauth-discovery.yaml"
    )

    for content in (nginx, helm_nginx, next_config, ingress):
        assert "/oauth-provider/metadata" in content
        assert "/mcp-oauth/metadata" not in content

    assert (
        r"^/\.well-known/oauth-authorization-server(/.*)?/api/oauth-provider/?$"
        in nginx
    )
    assert 'source: "/.well-known/oauth-authorization-server/:path*"' in next_config
    assert r"path: /\.well-known/oauth-authorization-server(/|$)(.*)" in ingress
    assert ingress.count("pathType: ImplementationSpecific") == 2
    assert ingress.count('nginx.ingress.kubernetes.io/use-regex: "true"') == 2
    assert "proxy_pass http://mcp_server;" in nginx
    assert (
        "destination: `${\n"
        '          process.env.MCP_INTERNAL_URL || "http://127.0.0.1:8090"\n'
        "        }/.well-known/oauth-protected-resource/:path*`"
    ) in next_config


def test_deployment_restarts_nginx_and_documents_the_provider_flag() -> None:
    values = _read("deployment/helm/charts/onyx/values.yaml")
    docker_env = _read("deployment/docker_compose/env.template")
    cli_docker_env = _read(
        "cli/internal/deploy/deployfiles/embedded/docker_compose/env.template"
    )

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
    assert "# OAUTH_PROVIDER_ENABLED=false" in docker_env
    assert "# OAUTH_PROVIDER_ENABLED=false" in cli_docker_env


def test_ingress_discovery_patterns_match_only_literal_well_known_paths() -> None:
    template = _read(
        "deployment/helm/charts/onyx/templates/ingress-mcp-oauth-discovery.yaml"
    )
    paths = re.findall(r"- path: (.+)", template)
    assert len(paths) == 2
    for path in paths:
        pattern = re.compile("^" + path)
        literal = path.removesuffix("(/|$)(.*)").replace(r"\.", ".")
        assert pattern.fullmatch(literal)
        assert pattern.fullmatch(literal + "/api/oauth-provider")
        assert not pattern.match(literal.replace("/.well-known", "/xwell-known"))
        assert not pattern.match(literal + "-unrelated")
