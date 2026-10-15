"""CI wiring checks, not evidence that Firecracker or browser flows passed."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.common.paths import find_ancestor_containing

_REPO_ROOT = find_ancestor_containing("deployment/helm/dev")
_WORKFLOW = _REPO_ROOT / ".github/workflows/pr-craft-k8s-tests.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW.read_text())


@pytest.mark.parametrize("missing_product_shard", [False, True])
def test_ci_requires_the_product_acceptance_shard(
    tmp_path: Path, missing_product_shard: bool
) -> None:
    steps = _workflow()["jobs"]["discover-test-files"]["steps"]
    discovery = next(step["run"] for step in steps if step.get("id") == "set-matrix")
    output = tmp_path / "github-output"
    root = _REPO_ROOT
    if missing_product_shard:
        root = tmp_path / "repo"
        test_dir = root / "backend/tests/integration/tests/craft/k8s"
        test_dir.mkdir(parents=True)
        (test_dir / "test_other.py").touch()
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", discovery],
        cwd=root,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    if missing_product_shard:
        assert result.returncode != 0
        assert "session_provisioning_api" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    entries = json.loads(output.read_text().removeprefix("test-files="))
    expected = sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in (_REPO_ROOT / "backend/tests/integration/tests/craft/k8s").rglob(
            "test_*.py"
        )
    )
    assert sorted(entry["path"] for entry in entries) == expected
    assert sum(entry["name"] == "session_provisioning_api" for entry in entries) == 1
    assert all(set(entry) == {"path", "name"} for entry in entries)


def test_ci_routes_all_craft_shards_through_the_frontend() -> None:
    job = _workflow()["jobs"]["craft-k8s-tests"]
    assert job["env"]["SANDBOX_TEST_FRONTEND_URL"] == "http://127.0.0.1:3000"
    assert job["env"]["SANDBOX_TEST_FIRECRACKER"] == "true"
    assert job["env"]["SANDBOX_TEST_KUBE_CONTEXT"] == "kind-onyx-craft-ci"
    assert job["env"]["SANDBOX_TEST_IP_FAMILY"] == "ipv4"
    steps = job["steps"]
    frontend = next(
        step for step in steps if step.get("name") == "Forward chart frontend to runner"
    )
    assert "if" not in frontend
    assert "requires_frontend" not in _WORKFLOW.read_text()
    assert not any(step.get("name") == "Forward chart API to runner" for step in steps)


def test_ci_runs_craft_browser_acceptance_after_api_acceptance() -> None:
    steps = _workflow()["jobs"]["craft-k8s-tests"]["steps"]
    api_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("Run Craft K8s tests")
    )
    browser_index, browser = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name") == "Run Craft browser acceptance"
    )
    assert browser_index > api_index
    assert browser["if"] == "matrix.test-file.name == 'session_provisioning_api'"
    assert browser["env"]["ENABLE_CRAFT"] == "true"
    assert browser["env"]["BASE_URL"] == "http://127.0.0.1:3000"
    assert browser["env"]["MOCK_LLM_SERVER_URL"] == "http://127.0.0.1:8095"
    assert browser["env"]["MOCK_LLM_BACKEND_URL"] == (
        "http://craft-mock-llm.onyx.svc.cluster.local:8095"
    )
    command = browser["run"]
    assert "bun run playwright" in command
    assert "tests/e2e/craft/craft_session_flow.spec.ts" in command
    assert "tests/e2e/craft/attachments.spec.ts" in command
    assert "--workers 1 --retries 0" in command


def test_ci_installs_policy_enforcement_before_kata() -> None:
    steps = _workflow()["jobs"]["craft-k8s-tests"]["steps"]
    config = next(step for step in steps if step.get("name") == "Write kind config")
    assert "disableDefaultCNI: true" in config["run"]
    assert "podSubnet: 192.168.0.0/16" in config["run"]
    create = next(step for step in steps if step.get("name") == "Create kind cluster")
    assert create["with"]["wait"] == "0s"
    cni_index, cni = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name") == "Install pinned policy-enforcing CNI"
    )
    kata_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Install and verify Kata Firecracker runtime"
    )
    assert cni_index < kata_index
    assert "/calico/v3.31.7/manifests/calico.yaml" in cni["run"]
    assert "sha256sum --check" in cni["run"]
    assert "rollout status daemonset/calico-node" in cni["run"]
    assert "--for=condition=Ready node --all" in cni["run"]


def test_ci_kubectl_matches_the_test_cluster_version() -> None:
    workflow = _workflow()
    create = next(
        step
        for step in workflow["jobs"]["craft-k8s-tests"]["steps"]
        if step.get("name") == "Create kind cluster"
    )
    node_version = create["with"]["node_image"].partition(":")[2].partition("@")[0]
    assert workflow["env"]["KUBECTL_VERSION"] == node_version


def test_ci_result_artifacts_are_unique_per_run_attempt() -> None:
    uploads = [
        step
        for step in _workflow()["jobs"]["craft-k8s-tests"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert uploads
    assert all("${{ github.run_attempt }}" in step["with"]["name"] for step in uploads)
