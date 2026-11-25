"""Enrollment reports the pre-v5 install ID only when one is stored, and never creates one."""

import uuid
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.db.encrypted_kv_store import (
    delete_encrypted_kv,
    load_encrypted_kv,
    upsert_encrypted_kv,
)
from onyx.db.fleet_enrollment import get_legacy_customer_uuid
from onyx.key_value_store.interface import KvKeyNotFoundError, unwrap_str
from onyx.utils import fleet_telemetry


def _stored() -> str | None:
    try:
        return unwrap_str(load_encrypted_kv(KV_CUSTOMER_UUID_KEY))
    except KvKeyNotFoundError:
        return None


@pytest.fixture
def no_stored_uuid(
    db_session: Session,  # noqa: ARG001 - initializes SqlEngine
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Start without a stored install ID; put the database's own value back after."""
    original: str | None = _stored()
    if original is not None:
        delete_encrypted_kv(KV_CUSTOMER_UUID_KEY)
    try:
        yield
    finally:
        try:
            delete_encrypted_kv(KV_CUSTOMER_UUID_KEY)
        except KvKeyNotFoundError:
            pass
        if original is not None:
            upsert_encrypted_kv(KV_CUSTOMER_UUID_KEY, {"value": original})


@pytest.mark.usefixtures("no_stored_uuid")
def test_no_stored_id_reports_none_and_creates_none() -> None:
    assert get_legacy_customer_uuid() is None
    assert _stored() is None


@pytest.mark.usefixtures("no_stored_uuid")
def test_stored_id_is_reported() -> None:
    value: str = str(uuid.uuid4())
    upsert_encrypted_kv(KV_CUSTOMER_UUID_KEY, {"value": value.upper()})
    assert get_legacy_customer_uuid() == value
    assert _stored() == value.upper()


@pytest.mark.usefixtures("no_stored_uuid")
def test_an_unreadable_stored_id_is_not_sent() -> None:
    upsert_encrypted_kv(KV_CUSTOMER_UUID_KEY, {"value": "not-a-uuid"})
    with pytest.raises(ValueError):
        get_legacy_customer_uuid()
    assert fleet_telemetry.legacy_customer_uuid() is None
