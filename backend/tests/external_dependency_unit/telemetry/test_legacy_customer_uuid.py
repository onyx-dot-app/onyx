"""Enrollment reports the pre-v5 install ID only when one is stored, and never creates one."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.db.fleet_enrollment import get_legacy_customer_uuid
from onyx.db.models import EncryptedKeyValueStore
from onyx.key_value_store.interface import unwrap_str


@pytest.mark.usefixtures("tenant_context")
def test_reads_the_stored_install_id_without_creating_one(db_session: Session) -> None:
    query = select(EncryptedKeyValueStore).where(
        EncryptedKeyValueStore.key == KV_CUSTOMER_UUID_KEY
    )
    before: EncryptedKeyValueStore | None = db_session.scalars(query).first()
    found: str | None = get_legacy_customer_uuid()
    db_session.expire_all()
    after: EncryptedKeyValueStore | None = db_session.scalars(query).first()
    if before is None:
        assert found is None
        assert after is None
    else:
        assert found == unwrap_str(before.value.get_value(apply_mask=False))
        assert after is not None
