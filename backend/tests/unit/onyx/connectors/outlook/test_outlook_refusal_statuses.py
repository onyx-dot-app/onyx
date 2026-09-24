"""OutlookGraphError's verdicts agree with the shared Graph classifier: 403, 404
and 423 are a refused mailbox, 401, 429, 5xx and no status fail the attempt,
400 and 410 are neither."""

from __future__ import annotations

import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.outlook.errors import raise_for_graph_error
from onyx.connectors.outlook.models import OutlookGraphError


def _error(status: int | None) -> OutlookGraphError:
    return OutlookGraphError(status, "ErrorAccessDenied", "denied")


@pytest.mark.parametrize("status", [403, 404, 423])
def test_refused_mailbox_is_permanent_and_not_an_attempt_failure(
    status: int,
) -> None:
    error = _error(status)
    assert error.is_permanent_refusal is True
    assert error.fails_the_attempt is False


@pytest.mark.parametrize("status", [None, 401, 429, 503])
def test_call_failures_are_not_a_refused_mailbox(status: int | None) -> None:
    error = _error(status)
    assert error.is_permanent_refusal is False
    assert error.fails_the_attempt is True


@pytest.mark.parametrize("status", [400, 410])
def test_other_client_errors_are_neither(status: int) -> None:
    """Outlook's third bucket: neither verdict, so each caller handles the item."""
    error = _error(status)
    assert error.is_permanent_refusal is False
    assert error.fails_the_attempt is False


@pytest.mark.parametrize("status", [404, 423])
def test_validation_family_names_a_missing_or_locked_mailbox(status: int) -> None:
    """Both read as no usable mailbox, so the capability checks report them alike."""
    with pytest.raises(ConnectorValidationError, match="no usable mailbox"):
        raise_for_graph_error(_error(status), "denied")
