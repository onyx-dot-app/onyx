"""The import boundary check flags an import that breaks a contract at any
depth, honours allow-lists and recorded exceptions, reports an exception that
matches nothing, and rejects a contract that names a missing path."""

from pathlib import Path

import pytest
from scripts import check_import_boundaries
from scripts.check_import_boundaries import ConfigError, Contract

_FORBIDDEN_CONTRACT = """
[[contract]]
name = "ce-not-ee"
rule = "onyx must not import ee"
reason = "Community code runs without ee."
instead = "Use fetch_versioned_implementation."
source = ["onyx/"]
forbidden = ["ee"]
allowed = ["ee.onyx.allowed"]
"""

_EXCEPTION = """
[[contract.exception]]
importer = "onyx/chat/tier.py"
imports = "ee.onyx.tier"
reason = "Guarded by the edition check."
"""

_INDEPENDENCE_CONTRACT = """
[[contract]]
name = "connectors-independent"
rule = "A connector must not import another connector"
reason = "Each connector changes alone."
instead = "Move shared code to common/."
type = "independence"
container = "onyx/connectors"
shared = ["common"]
"""


def _backend(tmp_path: Path, config: str) -> list[Contract]:
    # onyx/chat has no __init__.py, like much of the real tree.
    for path in (
        "onyx/__init__.py",
        "onyx/chat/tier.py",
        "onyx/connectors/jira/connector.py",
        "onyx/connectors/slack/connector.py",
        "onyx/connectors/common/utils.py",
        "onyx/connectors/factory.py",
        "ee/onyx/tier.py",
        "ee/onyx/allowed.py",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).touch()
    config_path = tmp_path / "import_boundaries.toml"
    config_path.write_text(config)
    return check_import_boundaries.load_contracts(config_path, tmp_path)


def _flagged(
    tmp_path: Path, config: str, path: str, source: str
) -> tuple[list[str], list[str]]:
    violations, stale = check_import_boundaries.check_file(
        path, source, _backend(tmp_path, config), tmp_path
    )
    return [violation.module for violation in violations], stale


@pytest.mark.parametrize(
    "source",
    [
        "from ee.onyx.tier import get_tier",
        "import ee.onyx.tier",
        "from ee.onyx import tier",
        "def f() -> None:\n    from ee.onyx.tier import get_tier",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import ee.onyx.tier",
    ],
)
def test_forbidden_import_is_flagged_at_any_depth(tmp_path: Path, source: str) -> None:
    modules, _ = _flagged(tmp_path, _FORBIDDEN_CONTRACT, "onyx/chat/tier.py", source)
    assert len(modules) == 1
    assert modules[0].startswith("ee.onyx.tier")


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("onyx/chat/tier.py", "from onyx.connectors.factory import build"),
        ("onyx/chat/tier.py", "from ee.onyx.allowed import ok"),
        ("onyx/chat/tier.py", "import eerie"),
        ("ee/onyx/tier.py", "from ee.onyx.allowed import ok"),
    ],
)
def test_permitted_import_passes(tmp_path: Path, path: str, source: str) -> None:
    assert _flagged(tmp_path, _FORBIDDEN_CONTRACT, path, source) == ([], [])


def test_relative_import_resolves_before_the_check(tmp_path: Path) -> None:
    config = _FORBIDDEN_CONTRACT.replace('["ee"]', '["onyx.connectors"]').replace(
        'allowed = ["ee.onyx.allowed"]', ""
    )
    modules, _ = _flagged(
        tmp_path, config, "onyx/chat/tier.py", "from ..connectors import factory"
    )
    assert modules == ["onyx.connectors.factory"]


def test_recorded_exception_passes_and_covers_only_its_import(tmp_path: Path) -> None:
    config = _FORBIDDEN_CONTRACT + _EXCEPTION
    source = "from ee.onyx.tier import get_tier\nfrom ee.onyx.other import x"
    modules, stale = _flagged(tmp_path, config, "onyx/chat/tier.py", source)
    assert modules == ["ee.onyx.other.x"]
    assert stale == []


def test_exception_that_matches_nothing_is_reported(tmp_path: Path) -> None:
    config = _FORBIDDEN_CONTRACT + _EXCEPTION
    modules, stale = _flagged(tmp_path, config, "onyx/chat/tier.py", "import os")
    assert modules == []
    assert len(stale) == 1
    assert "ee.onyx.tier" in stale[0]


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        (
            "onyx/connectors/jira/connector.py",
            "from onyx.connectors.slack.connector import SlackConnector",
            ["onyx.connectors.slack.connector.SlackConnector"],
        ),
        (
            "onyx/connectors/jira/connector.py",
            "from onyx.connectors.common.utils import x",
            [],
        ),
        (
            "onyx/connectors/jira/connector.py",
            "from onyx.connectors.jira.utils import x",
            [],
        ),
        # A module in the container is not a sibling.
        (
            "onyx/connectors/jira/connector.py",
            "from onyx.connectors.factory import x",
            [],
        ),
        ("onyx/connectors/factory.py", "import onyx.connectors.slack.connector", []),
        # A shared sibling is held to the same rule.
        (
            "onyx/connectors/common/utils.py",
            "import onyx.connectors.jira.connector",
            ["onyx.connectors.jira.connector"],
        ),
    ],
)
def test_independence(
    tmp_path: Path, path: str, source: str, expected: list[str]
) -> None:
    modules, _ = _flagged(tmp_path, _INDEPENDENCE_CONTRACT, path, source)
    assert modules == expected


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('source = ["onyx/"]', 'source = ["onyxx/"]'),
        ('source = ["onyx/"]', 'source = ["onyx"]'),
        ('forbidden = ["ee"]', 'forbidden = ["enterprise"]'),
        ('reason = "Community code runs without ee."', 'reason = ""'),
        ('instead = "Use fetch_versioned_implementation."', ""),
        ('allowed = ["ee.onyx.allowed"]', 'alowed = ["ee.onyx.allowed"]'),
    ],
)
def test_contract_that_names_nothing_is_rejected(
    tmp_path: Path, old: str, new: str
) -> None:
    with pytest.raises(ConfigError):
        _backend(tmp_path, _FORBIDDEN_CONTRACT.replace(old, new))


def test_exception_needs_a_reason(tmp_path: Path) -> None:
    config = _FORBIDDEN_CONTRACT + _EXCEPTION.replace(
        'reason = "Guarded by the edition check."', ""
    )
    with pytest.raises(ConfigError):
        _backend(tmp_path, config)


def test_failure_message_names_contract_import_and_destination(
    tmp_path: Path,
) -> None:
    violations, _ = check_import_boundaries.check_file(
        "onyx/chat/tier.py",
        "import os\nfrom ee.onyx.tier import get_tier",
        _backend(tmp_path, _FORBIDDEN_CONTRACT),
        tmp_path,
    )
    message = check_import_boundaries.format_violation(violations[0])
    assert "backend/onyx/chat/tier.py:2" in message
    assert "ee.onyx.tier.get_tier" in message
    assert "ce-not-ee: onyx must not import ee" in message
    assert "Use fetch_versioned_implementation." in message


def test_repo_contracts_hold() -> None:
    assert check_import_boundaries.main([]) == 0
