"""Guard on the revert (cancel_new_embedding) path: during an INSTANT backfill there is no
secondary to cancel, so it must surface a CONFLICT rather than silently return 200."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.search_settings import cancel_new_embedding

_MODULE = "onyx.server.manage.search_settings"


@patch(f"{_MODULE}._active_port_settings", return_value=MagicMock())
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
def test_cancel_conflicts_during_instant_backfill(
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_active: MagicMock,  # noqa: ARG001
) -> None:
    # No secondary but an INSTANT backfill is still draining -> CONFLICT, not a silent 200.
    with pytest.raises(OnyxError) as exc:
        cancel_new_embedding(_=MagicMock(), db_session=MagicMock())
    assert exc.value.error_code == OnyxErrorCode.CONFLICT


@patch(f"{_MODULE}._active_port_settings", return_value=None)
@patch(f"{_MODULE}.get_secondary_search_settings", return_value=None)
def test_cancel_is_clean_noop_when_nothing_to_revert(
    mock_secondary: MagicMock,  # noqa: ARG001
    mock_active: MagicMock,  # noqa: ARG001
) -> None:
    # No secondary and no active backfill -> nothing to cancel, returns without error.
    assert cancel_new_embedding(_=MagicMock(), db_session=MagicMock()) is None
