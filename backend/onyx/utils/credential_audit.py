"""Call-site surface of credential-access audit events.

Emission is an Enterprise feature: ``emit_credential_access`` resolves to
``ee.onyx.utils.credential_audit`` when EE is loaded and does nothing
otherwise. See that module for the payload and the invariants.
"""

import logging

from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

_internal_logger = logging.getLogger(__name__)


def emit_credential_access(
    credential_type: str,
    provider: str | None,
    row_id: int | None,
    *,
    user_id: str | None = None,
    auth_type: str | None = None,
) -> None:
    """Emit one audit line for a credential decrypt when EE is loaded.

    Never raises: credential reads sit on the chat hot path and on connector
    indexing.
    """
    try:
        emit = fetch_ee_implementation_or_noop(
            "onyx.utils.credential_audit", "emit_credential_access"
        )
    except Exception:
        _internal_logger.warning(
            "Failed to load the credential audit emitter", exc_info=True
        )
        return
    # A missing EE module resolves to this CE function; calling it would recurse.
    if emit is emit_credential_access:
        return
    emit(
        credential_type,
        provider,
        row_id,
        user_id=user_id,
        auth_type=auth_type,
    )
