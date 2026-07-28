"""Shared fixtures for onyx unit tests."""

import logging
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _capture_audit_logger(
    caplog: pytest.LogCaptureFixture,
) -> Generator[None, None, None]:
    """Attach caplog's handler to ``onyx.audit`` so audit tests can assert on
    caplog: the subsystem sets ``propagate=False``, so records don't reach
    pytest's root handler. No-op for tests that emit no audit events.
    """
    audit_logger = logging.getLogger("onyx.audit")
    audit_logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        audit_logger.removeHandler(caplog.handler)
