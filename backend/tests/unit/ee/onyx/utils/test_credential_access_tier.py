"""The credential-access audit line follows the same Enterprise tier gate as
the rest of the audit stream."""

import logging

import pytest

from ee.onyx.utils import credential_audit
from ee.onyx.utils import tier as tier_module
from ee.onyx.utils.credential_audit import AUDIT_LOGGER_NAME, emit_credential_access
from onyx.server.settings.models import Tier

pytestmark = pytest.mark.usefixtures("enterprise_audit")


@pytest.mark.parametrize(
    ("tier", "expected_lines"),
    [(Tier.ENTERPRISE, 1), (Tier.BUSINESS, 0)],
)
def test_only_the_enterprise_tier_logs_credential_access(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tier: Tier,
    expected_lines: int,
) -> None:
    monkeypatch.setattr(tier_module, "get_tier", lambda tenant_id=None: tier)  # noqa: ARG005
    # Keep the test off the Redis dedup.
    monkeypatch.setattr(credential_audit, "_should_emit", lambda *_args: True)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        emit_credential_access("connector", "google_drive", 1, user_id="u-1")

    lines = [r for r in caplog.records if r.name == AUDIT_LOGGER_NAME]
    assert len(lines) == expected_lines
