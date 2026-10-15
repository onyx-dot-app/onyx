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
@pytest.mark.parametrize("product_only", [False, True])
def test_ci_requires_the_product_acceptance_shard(
    tmp_path: Path, missing_product_shard: bool, product_only: bool
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
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(output),
            "PRODUCT_ONLY": str(product_only).lower(),
        },
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
    if product_only:
        expected = [
            path
            for path in expected
            if path.endswith("test_session_provisioning_api.py")
        ]
    assert sorted(entry["path"] for entry in entries) == expected
    assert sum(entry["name"] == "session_provisioning_api" for entry in entries) == 1
    assert all(set(entry) == {"path", "name"} for entry in entries)


def test_ci_product_probe_is_opt_in_and_manual_only() -> None:
    events = yaml.load(_WORKFLOW.read_text(), Loader=yaml.BaseLoader)["on"]
    product_only = events["workflow_dispatch"]["inputs"]["product_only"]
    assert product_only["type"] == "boolean"
    assert product_only["default"] == "false"
    assert product_only["required"] == "false"
    discovery = next(
        step
        for step in _workflow()["jobs"]["discover-test-files"]["steps"]
        if step.get("id") == "set-matrix"
    )
    assert discovery["env"]["PRODUCT_ONLY"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.product_only || false }}"
    )


@pytest.mark.parametrize("changed", ["true", "false", None])
@pytest.mark.parametrize("key", ["", "nonsecret-ci-credential-sentinel"])
def test_ci_requires_credentials_only_for_relevant_craft_runs(
    changed: str | None, key: str
) -> None:
    guard = next(
        step
        for step in _workflow()["jobs"]["changes"]["steps"]
        if step.get("name") == "Require Craft integration credentials"
    )
    assert guard["env"]["CRAFT_K8S_CHANGED"] == (
        "${{ steps.filter.outputs.craft_k8s || 'true' }}"
    )
    env: dict[str, str] = {**os.environ, "OPENAI_API_KEY": key}
    env.pop("CRAFT_K8S_CHANGED", None)
    if changed is not None:
        env["CRAFT_K8S_CHANGED"] = changed
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", guard["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    missing_required_key = changed != "false" and not key
    assert (result.returncode != 0) == missing_required_key
    if missing_required_key:
        assert "OPENAI_API_KEY is required" in result.stderr
    assert "nonsecret-ci-credential-sentinel" not in result.stdout + result.stderr


@pytest.mark.parametrize("product_only", [False, True])
def test_ci_product_probe_cannot_report_full_suite_qualification(
    product_only: bool,
) -> None:
    job = _workflow()["jobs"]["craft-k8s-tests-required"]
    assert job["name"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.product_only "
        "&& 'craft-k8s-product-probe' || 'craft-k8s-tests-required' }}"
    )
    step = next(step for step in job["steps"] if step.get("name") == "Check job status")
    assert step["env"]["PRODUCT_ONLY"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.product_only || false }}"
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            "CHANGES_RESULT": "success",
            "RUN_TESTS": "true",
            "DISCOVER_RESULT": "success",
            "BUILD_RESULT": "success",
            "TEST_RESULT": "success",
            "PRODUCT_ONLY": str(product_only).lower(),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    if product_only:
        assert "full Craft suite before qualification" in result.stdout
        assert "All Craft tests passed" not in result.stdout
    else:
        assert "All Craft tests passed" in result.stdout


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


def test_ci_uses_the_production_sandbox_dependencies() -> None:
    images = _workflow()["jobs"]["build-images"]["strategy"]["matrix"]["include"]
    sandbox = next(image for image in images if image["image"] == "sandbox")
    assert sandbox["extra_build_args"] == "ENABLE_SKILLS=true"


def test_ci_retains_named_results_and_successful_stdout_receipts() -> None:
    steps = _workflow()["jobs"]["craft-k8s-tests"]["steps"]
    test_index, test = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name", "").startswith("Run Craft K8s tests")
    )
    command = test["run"]
    assert (
        '--junitxml="${RUNNER_TEMP}/craft-k8s-results/${{ matrix.test-file.name }}.xml"'
        in command
    )
    assert "-o junit_family=xunit1" in command
    assert "-o junit_logging=system-out" in command
    assert "-o junit_log_passing_tests=true" in command
    upload_index, upload = next(
        (index, step)
        for index, step in enumerate(steps)
        if step.get("name") == "Upload Craft K8s results"
    )
    assert upload_index == test_index + 1
    assert upload["if"] == "always()"
    assert upload["uses"] == (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    )
    assert upload["with"] == {
        "name": (
            "craft-k8s-results-${{ matrix.test-file.name }}-"
            "${{ github.run_id }}-${{ github.run_attempt }}"
        ),
        "path": "${{ runner.temp }}/craft-k8s-results/${{ matrix.test-file.name }}.xml",
        "if-no-files-found": "ignore",
        "retention-days": 7,
    }


def test_ci_result_artifacts_are_unique_per_run_attempt() -> None:
    uploads = [
        step
        for step in _workflow()["jobs"]["craft-k8s-tests"]["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert uploads
    assert all("${{ github.run_attempt }}" in step["with"]["name"] for step in uploads)
