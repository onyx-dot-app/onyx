"""The snapshot tells clients whether a file is usable before indexing ends."""

import datetime
from uuid import uuid4

from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.server.features.projects.models import UserFileSnapshot


def test_snapshot_exposes_content_ready() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    user_file = UserFile(
        id=uuid4(),
        user_id=uuid4(),
        name="doc.pdf",
        file_id="path/doc",
        created_at=now,
        last_accessed_at=now,
        status=UserFileStatus.PROCESSING,
        content_type="application/pdf",
        token_count=7,
        chunk_count=None,
    )
    assert UserFileSnapshot.from_model(user_file).content_ready is True
