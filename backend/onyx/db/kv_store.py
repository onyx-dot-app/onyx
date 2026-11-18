"""Row operations for the plain ``key_value_store`` table (``KVStore``).

The cache layer and the transaction handling stay with the callers. For the encrypted
table, see ``onyx.db.encrypted_kv_store``."""

from sqlalchemy.orm import Session

from onyx.db.models import KVStore
from onyx.utils.special_types import JSON_ro


def fetch_kv_store_row(db_session: Session, key: str) -> KVStore | None:
    return db_session.query(KVStore).filter_by(key=key).first()


def add_kv_store_row__no_commit(db_session: Session, key: str, value: JSON_ro) -> None:
    db_session.add(KVStore(key=key, value=value))


def delete_kv_store_row__no_commit(db_session: Session, key: str) -> int:
    """Returns the number of deleted rows."""
    return db_session.query(KVStore).filter_by(key=key).delete()
