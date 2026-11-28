"""The CE audit surfaces never call themselves when the EE module is missing."""

import pytest

from onyx.utils import audit as audit_surface
from onyx.utils import credential_audit as credential_audit_surface
from onyx.utils.audit import AuditAction, AuditOutcome


def test_audit_surface_does_not_recurse(monkeypatch: pytest.MonkeyPatch) -> None:
    # A missing EE module makes the fetch fall back to the CE surface itself.
    monkeypatch.setattr(
        audit_surface,
        "fetch_ee_implementation_or_noop",
        lambda *_args: audit_surface.emit_audit_event,
    )

    audit_surface.emit_audit_event(AuditAction.LOGOUT, AuditOutcome.SUCCESS)


def test_credential_surface_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credential_audit_surface,
        "fetch_ee_implementation_or_noop",
        lambda *_args: credential_audit_surface.emit_credential_access,
    )

    credential_audit_surface.emit_credential_access("connector", "slack", 1)
