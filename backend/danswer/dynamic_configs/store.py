import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from filelock import FileLock
from sqlalchemy.orm import Session

from danswer.db.engine import get_session_factory
from danswer.db.models import KVStore
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.dynamic_configs.interface import DynamicConfigStore
from danswer.dynamic_configs.interface import JSON_ro


FILE_LOCK_TIMEOUT = 10


def _get_file_lock(file_name: Path) -> FileLock:
    return FileLock(file_name.with_suffix(".lock"))


class FileSystemBackedDynamicConfigStore(DynamicConfigStore):
    def __init__(self, dir_path: str) -> None:
        # TODO (chris): maybe require all possible keys to be passed in
        # at app start somehow to prevent key overlaps
        self.dir_path = Path(dir_path)

    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        file_path = self.dir_path / key
        lock = _get_file_lock(file_path)
        with lock.acquire(timeout=FILE_LOCK_TIMEOUT):
            with open(file_path, "w+") as f:
                json.dump(val, f)

    def load(self, key: str) -> JSON_ro:
        file_path = self.dir_path / key
        if not file_path.exists():
            raise ConfigNotFoundError
        lock = _get_file_lock(file_path)
        with lock.acquire(timeout=FILE_LOCK_TIMEOUT):
            with open(self.dir_path / key) as f:
                return cast(JSON_ro, json.load(f))

    def delete(self, key: str) -> None:
        file_path = self.dir_path / key
        if not file_path.exists():
            raise ConfigNotFoundError
        lock = _get_file_lock(file_path)
        with lock.acquire(timeout=FILE_LOCK_TIMEOUT):
            os.remove(file_path)


class PostgresBackedDynamicConfigStore(DynamicConfigStore):
    @contextmanager
    def get_session(self) -> Iterator[Session]:
        factory = get_session_factory()
        session: Session = factory()
        try:
            yield session
        finally:
            session.close()

    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        # The actual encryption/decryption is done in Postgres, we just need to choose
        # which field to set
        encrypted_val = val if encrypt else None
        plain_val = val if not encrypt else None
        with self.get_session() as session:
            obj = session.query(KVStore).filter_by(key=key).first()
            if obj:
                obj.value = plain_val
                obj.encrypted_value = encrypted_val
            else:
                obj = KVStore(
                    key=key, value=plain_val, encrypted_value=encrypted_val
                )  # type: ignore
                session.query(KVStore).filter_by(key=key).delete()  # just in case
                session.add(obj)
            session.commit()

    def load(self, key: str) -> JSON_ro:
        with self.get_session() as session:
            obj = session.query(KVStore).filter_by(key=key).first()
            if not obj:
                raise ConfigNotFoundError

            if obj.value is not None:
                return cast(JSON_ro, obj.value)
            if obj.encrypted_value is not None:
                return cast(JSON_ro, obj.encrypted_value)

            return None

    def delete(self, key: str) -> None:
        with self.get_session() as session:
            result = session.query(KVStore).filter_by(key=key).delete()  # type: ignore
            if result == 0:
                raise ConfigNotFoundError
            session.commit()
