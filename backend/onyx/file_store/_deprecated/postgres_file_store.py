from typing import Any
from typing import cast
from typing import IO

import puremagic
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import FileStore as FileStoreModel
from onyx.db.pg_file_store import create_populate_lobj
from onyx.db.pg_file_store import delete_filestore_by_file_name
from onyx.db.pg_file_store import delete_lobj_by_id
from onyx.db.pg_file_store import get_filestore_by_file_name
from onyx.db.pg_file_store import get_filestore_by_file_name_optional
from onyx.db.pg_file_store import read_lobj
from onyx.db.pg_file_store import upsert_filestore_postgres
from onyx.file_store.file_store import FileStore
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PostgresBackedFileStore(FileStore):
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session

    def initialize(self) -> None:
        pass

    def has_file(
        self,
        file_name: str,
        file_origin: FileOrigin,
        file_type: str,
        display_name: str | None = None,
    ) -> bool:
        file_record = get_filestore_by_file_name_optional(
            file_name=display_name or file_name, db_session=self.db_session
        )
        return (
            file_record is not None
            and file_record.file_origin == file_origin
            and file_record.file_type == file_type
            and file_record.lobj_oid is not None  # Ensure it's a PostgreSQL file
        )

    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            # The large objects in postgres are saved as special objects can be listed with
            # SELECT * FROM pg_largeobject_metadata;
            obj_id = create_populate_lobj(content=content, db_session=self.db_session)
            upsert_filestore_postgres(
                file_name=file_name,
                display_name=display_name or file_name,
                file_origin=file_origin,
                file_type=file_type,
                lobj_oid=obj_id,
                db_session=self.db_session,
                file_metadata=file_metadata,
            )
            self.db_session.commit()
        except Exception:
            self.db_session.rollback()
            raise

    def read_file(
        self, file_name: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO[bytes]:
        file_record = get_filestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )
        if file_record.lobj_oid is None:
            raise RuntimeError(f"File {file_name} is not stored in PostgreSQL")
        return read_lobj(
            lobj_oid=file_record.lobj_oid,
            db_session=self.db_session,
            mode=mode,
            use_tempfile=use_tempfile,
        )

    def read_file_record(self, file_name: str) -> FileStoreModel:
        file_record = get_filestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )
        return file_record

    def delete_file(self, file_name: str) -> None:
        try:
            file_record = get_filestore_by_file_name(
                file_name=file_name, db_session=self.db_session
            )
            if file_record.lobj_oid is not None:
                delete_lobj_by_id(file_record.lobj_oid, db_session=self.db_session)
            delete_filestore_by_file_name(
                file_name=file_name, db_session=self.db_session
            )
            self.db_session.commit()
        except Exception:
            self.db_session.rollback()
            raise

    def get_file_with_mime_type(self, filename: str) -> FileWithMimeType | None:
        mime_type: str = "application/octet-stream"
        try:
            file_io = self.read_file(filename, mode="b")
            file_content = file_io.read()
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)
            return FileWithMimeType(data=file_content, mime_type=mime_type)
        except Exception:
            return None
