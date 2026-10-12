"""Integration tests for the draft check plan endpoint: the checks a run would
hold for an unsaved connector form, listed before anything runs."""

from typing import Any

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import DraftCheckStateKind
from onyx.db.enums import AccessType
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_PLAN_URL = f"{API_SERVER_URL}/manage/admin/connector-checks/plan"

# A plan decides states only; nothing has run.
_UNRUN_STATES = {
    DraftCheckStateKind.PENDING.value,
    DraftCheckStateKind.WAITING.value,
    DraftCheckStateKind.NOT_APPLICABLE.value,
}


def _plan(user: DATestUser, body: dict[str, Any]) -> requests.Response:
    return client.post(_PLAN_URL, json=body, headers=user.headers)


def test_source_without_named_checks_plans_the_fallback_check(
    admin_user: DATestUser,
) -> None:
    # Under test: no credential, no form values.
    response = _plan(admin_user, {"source": DocumentSource.GITHUB.value})

    # Postcondition: the one fallback check, waiting for a complete config.
    response.raise_for_status()
    plan = response.json()
    assert plan["source"] == DocumentSource.GITHUB.value
    assert [check["check_id"] for check in plan["checks"]] == [
        "github_connector_settings"
    ]
    fallback = plan["checks"][0]
    assert fallback["required"] is True
    assert fallback["state"] == DraftCheckStateKind.WAITING.value
    assert "run_id" not in plan


def test_named_checks_plan_with_their_required_flags(
    admin_user: DATestUser,
) -> None:
    # Under test.
    response = _plan(
        admin_user,
        {
            "source": DocumentSource.CONFLUENCE.value,
            "access_type": AccessType.PUBLIC.value,
            "form_state": {},
        },
    )

    # Postcondition: named checks replace the fallback, some of them optional,
    # and none has run.
    response.raise_for_status()
    checks = response.json()["checks"]
    check_ids = [check["check_id"] for check in checks]
    assert "confluence_connector_settings" not in check_ids
    assert any(check["required"] for check in checks)
    assert any(not check["required"] for check in checks)
    assert {check["state"] for check in checks} <= _UNRUN_STATES
    assert all(check["duration_ms"] is None for check in checks)


def test_form_errors_come_back_without_starting_a_run(
    admin_user: DATestUser,
) -> None:
    # Under test: a value of the wrong type and a field the config lacks.
    response = _plan(
        admin_user,
        {
            "source": DocumentSource.CONFLUENCE.value,
            "form_state": {"is_cloud": "not-a-bool", "no_such_field": 1},
        },
    )

    # Postcondition.
    response.raise_for_status()
    plan = response.json()
    assert "is_cloud" in plan["form_errors"]
    assert plan["unknown_fields"] == ["no_such_field"]


def test_basic_user_cannot_plan(basic_user: DATestUser) -> None:
    # Under test.
    response = _plan(basic_user, {"source": DocumentSource.GITHUB.value})

    # Postcondition.
    assert response.status_code == 403
