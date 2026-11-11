from typing import Any

import yaml

from tests.external_dependency_unit.craft_helm.rendering import render_chart


def test_sandbox_manager_can_inventory_all_runtime_resources() -> None:
    result = render_chart()
    assert result.returncode == 0, result.stderr
    resources: list[dict[str, Any]] = [
        r for r in yaml.safe_load_all(result.stdout) if r
    ]
    role = next(
        r
        for r in resources
        if r["kind"] == "Role" and r["metadata"]["name"].endswith("sandbox-manager")
    )
    for kind in ("pods", "services", "secrets"):
        rule = next(rule for rule in role["rules"] if kind in rule["resources"])
        assert {"get", "list", "delete"}.issubset(rule["verbs"])
    assert role["metadata"]["namespace"] == "onyx-sandboxes"
