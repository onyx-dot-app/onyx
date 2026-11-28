from unittest.mock import MagicMock

import pytest

from onyx.db.enums import PortAttemptStatus
from onyx.db.port_attempt import mark_port_terminal


@pytest.mark.parametrize(
    "status",
    [
        PortAttemptStatus.NOT_STARTED,
        PortAttemptStatus.IN_PROGRESS,
        PortAttemptStatus.PAUSED,
    ],
)
def test_mark_port_terminal_rejects_non_terminal_status(
    status: PortAttemptStatus,
    mock_db_session: MagicMock,
) -> None:
    with pytest.raises(ValueError, match="Expected a terminal port status"):
        mark_port_terminal(mock_db_session, 1, status, error_msg="invalid transition")

    assert mock_db_session.mock_calls == []
