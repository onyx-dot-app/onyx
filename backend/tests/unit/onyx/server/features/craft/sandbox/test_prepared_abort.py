from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.serve_transport import _ServeMixin


def test_prepared_abort_defers_request_and_closes_client_on_rejected_target() -> None:
    transport = MagicMock(spec=_ServeMixin)
    transport._session_directory.return_value = "/workspace/session"
    client = transport._build_serve_client.return_value
    with _ServeMixin.prepare_opencode_abort(
        transport, uuid4(), uuid4(), "opencode-session"
    ) as abort:
        assert abort is not None
        client.abort.assert_not_called()
    client.abort.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize("preparation_fails", [False, True])
def test_prepared_abort_preserves_best_effort_transport_errors(
    preparation_fails: bool,
) -> None:
    transport = MagicMock(spec=_ServeMixin)
    transport._session_directory.return_value = "/workspace/session"
    client = transport._build_serve_client.return_value
    if preparation_fails:
        transport._build_serve_client.side_effect = RuntimeError(
            "control plane unavailable"
        )
    else:
        client.abort.side_effect = RuntimeError("abort unavailable")
    with _ServeMixin.prepare_opencode_abort(
        transport, uuid4(), uuid4(), "opencode-session"
    ) as abort:
        if preparation_fails:
            assert abort is None
        else:
            assert abort is not None
            abort()
    if not preparation_fails:
        client.close.assert_called_once()
