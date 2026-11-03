"""Each Linear check maps the gateway's answer onto a validation outcome: a
refused credential, a scope entry Linear does not answer for, or an empty
scope."""

from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
)
from onyx.connectors.linear.capability_checks import (
    build_linear_indexing_checks,
)
from onyx.connectors.linear.models import (
    LinearProject,
    LinearViewer,
)
from onyx.connectors.linear.source_operations import (
    LinearAuthError,
    LinearSourceOperations,
)


def _check(checks: list[CapabilityCheck], check_id: str) -> CapabilityCheck:
    return next(check for check in checks if check.check_id == check_id)


def _context(
    ops: MagicMock, config: dict[str, Any] | None = None
) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.LINEAR,
        credential_json={},
        connector_specific_config=config,
        source_operations=ops,
    )


def _ops() -> MagicMock:
    ops = create_autospec(LinearSourceOperations, instance=True)
    ops.get_viewer.return_value = LinearViewer(guest=False)
    return ops


def test_the_token_check_turns_a_refusal_into_a_credential_error() -> None:
    ops = _ops()
    ops.get_viewer.side_effect = LinearAuthError(
        "refused", status_code=401, body="refused"
    )
    check = _check(build_linear_indexing_checks(), "linear_token")

    with pytest.raises(CredentialInvalidError):
        check.run(_context(ops))


def test_the_teams_check_applies_only_when_teams_are_configured() -> None:
    check = _check(build_linear_indexing_checks(), "linear_teams")
    form = _context(_ops(), {"team_keys": []}).form_state
    assert form is not None and not check.applies(form)
    form = _context(_ops(), {"team_keys": ["eng"]}).form_state
    assert form is not None and check.applies(form)


def test_the_teams_check_names_the_missing_keys() -> None:
    ops = _ops()
    ops.list_team_keys.return_value = {"ENG"}
    check = _check(build_linear_indexing_checks(), "linear_teams")

    with pytest.raises(ConnectorValidationError) as error:
        check.run(_context(ops, {"team_keys": ["eng", "des"]}))

    assert error.value.summary == "Team not found: DES"
    ops.list_team_keys.assert_called_once_with(keys=["DES", "ENG"])


def test_the_teams_check_fails_when_no_team_is_found() -> None:
    ops = _ops()
    ops.list_team_keys.return_value = set()
    check = _check(build_linear_indexing_checks(), "linear_teams")

    with pytest.raises(ConnectorValidationError, match="not found: DES"):
        check.run(_context(ops, {"team_keys": ["des"]}))


def test_the_projects_check_names_the_missing_entries() -> None:
    ops = _ops()
    ops.list_projects.return_value = [LinearProject(name="Roadmap", slug_id="x")]
    check = _check(build_linear_indexing_checks(), "linear_projects")

    with pytest.raises(ConnectorValidationError) as error:
        check.run(_context(ops, {"projects": ["Roadmap", "Gone"]}))

    assert error.value.summary == "Project not found: Gone"


def test_the_issues_check_reads_one_scoped_page() -> None:
    ops = _ops()
    ops.iterate_issues.return_value = iter([[{"identifier": "ENG-1"}]])
    check = _check(build_linear_indexing_checks(), "linear_issues")

    output = check.run(_context(ops, {"team_keys": ["ENG"]}))

    assert output is not None and output.summary == "Read issue ENG-1"
    ops.iterate_issues.assert_called_once_with(
        issue_filter={"updatedAt": {}, "team": {"key": {"in": ["ENG"]}}}, page_size=1
    )
