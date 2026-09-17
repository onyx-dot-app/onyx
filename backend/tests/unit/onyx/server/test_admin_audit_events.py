"""Unit tests for audit-event emission from admin-config / access-control seams.

The API-key endpoints are the thinnest admin endpoints (each just calls one DB
function then emits), so they're used here as representatives of the uniform
emit-on-success wiring shared by the LLM-provider, connector, cc-pair,
credential, and user endpoints. Emission itself is covered in
tests/unit/onyx/utils/test_audit.py.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from onyx.server.api_key.api import (
    create_api_key,
    delete_api_key,
    regenerate_existing_api_key,
    update_existing_api_key,
)
from onyx.server.manage.llm.api import delete_llm_provider
from tests.utils.audit import audit_events


@patch("onyx.server.api_key.api.insert_api_key")
def test_create_api_key_emits_event(
    mock_insert: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_insert.return_value = MagicMock(api_key_id=7)
    user = MagicMock(id="admin-1", email="admin@example.com")

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        create_api_key(MagicMock(), user=user, db_session=MagicMock())

    events = audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "api_key.create"
    assert events[0]["outcome"] == "success"
    assert events[0]["resource_type"] == "api_key"
    assert events[0]["resource_id"] == "7"
    assert events[0]["actor"]["email"] == "admin@example.com"


@patch("onyx.server.api_key.api.regenerate_api_key")
def test_regenerate_api_key_emits_event(
    _mock_regen: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = MagicMock(id="admin-1", email="admin@example.com")

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        regenerate_existing_api_key(api_key_id=42, user=user, db_session=MagicMock())

    events = audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "api_key.regenerate"
    assert events[0]["resource_id"] == "42"


@patch("onyx.server.api_key.api.update_api_key")
def test_update_api_key_emits_event(
    _mock_update: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Updating a key replaces every group the service account belongs to, and
    those groups are what grant it permissions — so the groups are in the payload."""
    user = MagicMock(id="admin-1", email="admin@example.com")
    args = MagicMock(name="ci-key", group_ids=[3, 9])

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        update_existing_api_key(
            api_key_id=42, api_key_args=args, user=user, db_session=MagicMock()
        )

    events = audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "api_key.update"
    assert events[0]["resource_id"] == "42"
    assert events[0]["extra"]["group_ids"] == [3, 9]


@patch("onyx.server.api_key.api.remove_api_key")
def test_delete_api_key_emits_event(
    _mock_remove: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = MagicMock(id="admin-1", email="admin@example.com")

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        delete_api_key(api_key_id=99, user=user, db_session=MagicMock())

    events = audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "api_key.delete"
    assert events[0]["outcome"] == "success"
    assert events[0]["resource_id"] == "99"


@patch("onyx.server.manage.llm.api.invalidate_provider_listing_cache")
@patch("onyx.server.manage.llm.api.remove_llm_provider")
def test_delete_llm_provider_emits_event(
    _mock_remove: MagicMock,
    _mock_invalidate: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = MagicMock(id="admin-1", email="admin@example.com")

    with caplog.at_level(logging.INFO, logger="onyx.audit"):
        # force=True skips the default-provider lookup so no DB is needed.
        delete_llm_provider(
            provider_id=5, force=True, user=user, db_session=MagicMock()
        )

    events = audit_events(caplog)
    assert len(events) == 1
    assert events[0]["action"] == "llm_provider.delete"
    assert events[0]["ocsf_class"] == "api_activity"
    assert events[0]["resource_id"] == "5"
