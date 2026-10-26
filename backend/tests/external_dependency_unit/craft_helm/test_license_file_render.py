"""Render the documented startup license mount with the shared Helm runner."""

import json
from pathlib import Path
from typing import cast

import pytest
import yaml
from kubernetes import client
from urllib3.response import HTTPResponse

from tests.common.paths import find_ancestor_containing
from tests.external_dependency_unit.craft_helm.rendering import (
    render_chart,
    skip_or_fail,
)


@pytest.mark.parametrize("configured", [False, True])
def test_api_license_file_mount(configured: bool, tmp_path: Path) -> None:
    extra_args = ["--show-only", "templates/api-deployment.yaml"]
    if configured:
        repo_root = find_ancestor_containing("deployment/helm/charts/onyx")
        readme = (repo_root / "deployment/helm/README.md").read_text()
        section = readme.split("## Load a license file at startup\n", 1)[1]
        values = section.split("```yaml\n", 1)[1].split("```", 1)[0]
        values_file = tmp_path / "license-values.yaml"
        values_file.write_text(values)
        extra_args.extend(
            [
                "-f",
                str(values_file),
                "--set",
                "api.securityContext.runAsNonRoot=true,api.securityContext.runAsUser=1000",
            ]
        )

    result = render_chart(extra_args)
    if result.returncode != 0:
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    response = HTTPResponse(body=json.dumps(yaml.safe_load(result.stdout)).encode())
    deployment = cast(
        client.V1Deployment,
        client.ApiClient().deserialize(response, "V1Deployment"),
    )
    assert deployment.spec is not None
    assert deployment.spec.template.spec is not None
    pod = deployment.spec.template.spec
    api = next(
        container for container in pod.containers if container.name == "api-server"
    )
    env = {item.name: item.value for item in api.env or []}
    volumes = {volume.name: volume for volume in pod.volumes or []}
    mounts = {mount.name: mount for mount in api.volume_mounts or []}

    if not configured:
        assert "ONYX_LICENSE_FILE" not in env
        assert "onyx-license" not in volumes
        assert "onyx-license" not in mounts
        return

    assert env["ONYX_LICENSE_FILE"] == "/etc/onyx/license/license.lic"
    assert api.security_context is not None
    assert api.security_context.run_as_non_root is True
    assert api.security_context.run_as_user == 1000
    assert mounts["onyx-license"].mount_path == "/etc/onyx/license"
    assert mounts["onyx-license"].read_only is True
    secret = volumes["onyx-license"].secret
    assert secret is not None
    assert secret.secret_name == "onyx-license"
    assert secret.default_mode == 0o440
    assert [(item.key, item.path) for item in secret.items or []] == [
        ("license.lic", "license.lic")
    ]
    assert pod.security_context is not None
    assert pod.security_context.fs_group == 1000
