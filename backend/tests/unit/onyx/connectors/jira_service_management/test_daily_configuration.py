"""Keep optional JSM tests from adding unnecessary session-wide secrets."""

import runpy
from pathlib import Path

import pytest

from tests.utils.secret_names import TestSecret


@pytest.mark.parametrize(
    "project,custom_url,expected",
    [
        (False, False, set()),
        (False, True, set()),
        (True, True, {TestSecret.JIRA_USER_EMAIL, TestSecret.JIRA_API_TOKEN}),
        (
            True,
            False,
            {
                TestSecret.JIRA_USER_EMAIL,
                TestSecret.JIRA_API_TOKEN,
                TestSecret.JIRA_BASE_URL,
            },
        ),
    ],
)
def test_daily_test_declares_only_configured_secrets(
    monkeypatch: pytest.MonkeyPatch,
    project: bool,
    custom_url: bool,
    expected: set[TestSecret],
    pytestconfig: pytest.Config,
) -> None:
    """Collect the module without resolving secrets or contacting a Jira server."""
    pytestconfig.addinivalue_line(
        "markers", "secrets(*secrets): required test settings"
    )
    for name, enabled, value in [
        ("JIRA_SERVICE_MANAGEMENT_PROJECT_KEY", project, "HELP"),
        ("JIRA_SERVICE_MANAGEMENT_BASE_URL", custom_url, "https://jira.example.test"),
    ]:
        if enabled:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    path = (
        Path(__file__).resolve().parents[4]
        / "daily/connectors/jira_service_management/test_jira_service_management_basic.py"
    )
    module = runpy.run_path(str(path))
    marks = module["pytestmark"]
    declared = {
        secret for mark in marks if mark.name == "secrets" for secret in mark.args
    }
    assert declared == expected
    skip = next(mark for mark in marks if mark.name == "skipif")
    assert skip.args == (not project,)
