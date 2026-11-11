from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from io import BytesIO
from threading import Event, Lock
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.server.features.build.session import api as session_api


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_file_mutation_waits_for_cleanup_lock(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, session_id = uuid4(), uuid4()
    lock = Lock()
    waiting, mutated = Event(), Event()
    manager = MagicMock()

    @contextmanager
    def creation_lock(requested_user_id: UUID) -> Generator[None, None, None]:
        assert requested_user_id == user_id
        waiting.set()
        with lock:
            yield

    def upload(**_kwargs: object) -> tuple[str, int]:
        mutated.set()
        return "attachments/test.txt", 4

    def delete(*_args: object) -> bool:
        mutated.set()
        return True

    manager.upload_file.side_effect = upload
    manager.delete_file.side_effect = delete
    monkeypatch.setattr(session_api, "SessionManager", lambda _db: manager)
    monkeypatch.setattr(session_api, "session_creation_lock", creation_lock)

    def request() -> None:
        user = cast(User, SimpleNamespace(id=user_id))
        db_session = cast(Session, MagicMock())
        if operation == "upload":
            response = session_api.upload_file_endpoint(
                session_id,
                file=UploadFile(filename="test.txt", file=BytesIO(b"test")),
                user=user,
                db_session=db_session,
            )
            assert response.path == "attachments/test.txt"
            assert response.size_bytes == 4
        else:
            deleted = session_api.delete_file_endpoint(
                session_id, "attachments/test.txt", user=user, db_session=db_session
            )
            assert deleted.status_code == 204

    with ThreadPoolExecutor(max_workers=1) as executor:
        with lock:
            future = executor.submit(request)
            assert waiting.wait(timeout=5)
            assert not mutated.is_set()
        future.result(timeout=5)
    assert mutated.is_set()
