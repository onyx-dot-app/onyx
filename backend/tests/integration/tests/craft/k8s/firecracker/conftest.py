"""Opt-in checks against an existing Firecracker-backed Craft deployment."""

import json
import os
import subprocess

import httpx
import pytest

from tests.common.craft.deployment_fixtures import (
    _reap_module_sandboxes as _reap_module_sandboxes,
)
from tests.common.craft.deployment_fixtures import (
    _run_migrations as _run_migrations,
)
from tests.common.craft.deployment_fixtures import (
    _start_celery_workers as _start_celery_workers,
)
from tests.common.craft.deployment_fixtures import _test_client as _test_client
from tests.common.craft.deployment_fixtures import initialize_db as initialize_db
from tests.common.craft.deployment_fixtures import (
    seed_dev_license_for_session as seed_dev_license_for_session,
)
from tests.integration.tests.craft.k8s.networking.test_networking import (
    kubectl,
    sandbox,
    sandbox_namespace,
)

other_sandbox = sandbox


@pytest.fixture(scope="session", autouse=True)
def deployed_frontend() -> str:
    if os.environ.get("SANDBOX_TEST_FIRECRACKER") != "true":
        pytest.skip("Set SANDBOX_TEST_FIRECRACKER=true to test the deployed runtime")
    for name in (
        "SANDBOX_TEST_FRONTEND_URL",
        "SANDBOX_TEST_KUBE_CONTEXT",
        "SANDBOX_TEST_IP_FAMILY",
    ):
        if not os.environ.get(name):
            pytest.fail(f"{name} is required for Firecracker deployment tests")
    if os.environ["SANDBOX_TEST_IP_FAMILY"] not in {"ipv4", "ipv6"}:
        pytest.fail("SANDBOX_TEST_IP_FAMILY must be ipv4 or ipv6")
    frontend = httpx.URL(os.environ["SANDBOX_TEST_FRONTEND_URL"])
    if frontend.scheme not in {"http", "https"} or frontend.path != "/":
        pytest.fail(
            "SANDBOX_TEST_FRONTEND_URL must be the frontend origin without /api"
        )
    try:
        runtime = json.loads(
            kubectl(sandbox_namespace(), "get", "runtimeclass", "kata-fc", "-o", "json")
        )
        template = json.loads(
            kubectl(
                sandbox_namespace(), "get", "podtemplate", "sandbox-pod", "-o", "json"
            )
        )
        prepullers = json.loads(
            kubectl(
                sandbox_namespace(),
                "get",
                "daemonsets",
                "-l",
                "app.kubernetes.io/component=sandbox-image-prepuller",
                "-o",
                "json",
            )
        )["items"]
    except subprocess.CalledProcessError as exc:
        pytest.fail(
            f"Firecracker deployment preflight failed: {exc.stderr.strip()}",
            pytrace=False,
        )
    assert runtime["handler"] == "kata-fc", (
        "RuntimeClass kata-fc must use handler kata-fc"
    )
    assert template["template"]["spec"].get("runtimeClassName") == "kata-fc", (
        "The deployed sandbox-pod PodTemplate must select runtimeClassName kata-fc"
    )
    for prepuller in prepullers:
        assert (
            prepuller["spec"]["template"]["spec"].get("runtimeClassName") == "kata-fc"
        ), "Enabled sandbox image prepullers must select runtimeClassName kata-fc"
    return str(frontend).rstrip("/")
