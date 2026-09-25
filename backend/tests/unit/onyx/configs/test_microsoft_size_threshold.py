"""The Microsoft file size caps resolve at import, so each case runs in a fresh
interpreter with its own environment."""

import json
import os
import subprocess
import sys

import pytest

_CAPS = (
    "SHAREPOINT_CONNECTOR_SIZE_THRESHOLD",
    "OUTLOOK_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD",
    "TEAMS_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD",
)
_DEFAULT = 20 * 1024 * 1024


def _resolve(env_overrides: dict[str, str]) -> dict[str, int]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _CAPS and key != "MICROSOFT_CONNECTOR_SIZE_THRESHOLD"
    }
    env.update(env_overrides)
    entries = ", ".join(f'"{name}": c.{name}' for name in _CAPS)
    script = (
        "import json; from onyx.configs import app_configs as c; "
        f"print(json.dumps({{{entries}}}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        cwd=os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."),
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_unset_leaves_every_cap_at_the_default() -> None:
    assert _resolve({}) == dict.fromkeys(_CAPS, _DEFAULT)


def test_shared_variable_sets_all_three() -> None:
    caps = _resolve({"MICROSOFT_CONNECTOR_SIZE_THRESHOLD": "1000"})
    assert caps == dict.fromkeys(_CAPS, 1000)


@pytest.mark.parametrize("own_name", _CAPS)
def test_per_connector_variable_wins_for_that_connector_only(own_name: str) -> None:
    caps = _resolve({"MICROSOFT_CONNECTOR_SIZE_THRESHOLD": "1000", own_name: "50"})
    assert caps[own_name] == 50
    assert all(caps[name] == 1000 for name in _CAPS if name != own_name)


def test_empty_string_means_unset() -> None:
    caps = _resolve({"MICROSOFT_CONNECTOR_SIZE_THRESHOLD": "", _CAPS[0]: ""})
    assert caps == dict.fromkeys(_CAPS, _DEFAULT)
