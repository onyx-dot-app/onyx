from abc import ABC
from abc import abstractmethod
from typing import cast
from typing import IO

import puremagic
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import PGFileStore
from onyx.db.pg_file_store import create_populate_lobj
from onyx.db.pg_file_store import delete_lobj_by_id
from onyx.db.pg_file_store import delete_pgfilestore_by_file_name
from onyx.db.pg_file_store import get_pgfilestore_by_file_name
from onyx.db.pg_file_store import get_pgfilestore_by_file_name_optional
from onyx.db.pg_file_store import read_lobj
from onyx.db.pg_file_store import upsert_pgfilestore
from onyx.utils.file import FileWithMimeType


class FileStore(ABC):
    """
    An abstraction for storing files and large binary objects.
    """

    @abstractmethod
    def has_file(
        self,
        file_name: str,
        file_origin: FileOrigin,
        file_type: str,
        display_name: str | None = None,
    ) -> bool:
        """
        Check if a file exists in the blob store

        Parameters:
        - file_name: Name of the file to save
        - display_name: Display name of the file
        - file_origin: Origin of the file
        - file_type: Type of the file
        """
        raise NotImplementedError

    @abstractmethod
    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict | None = None,
        commit: bool = True,
    ) -> None:
        """
        Save a file to the blob store

        Parameters:
        - connector_name: Name of the CC-Pair (as specified by the user in the UI)
        - file_name: Name of the file to save
        - content: Contents of the file
        - display_name: Display name of the file
        - file_origin: Origin of the file
        - file_type: Type of the file
        - file_metadata: Additional metadata for the file
        - commit: Whether to commit the transaction after saving the file
        """
        raise NotImplementedError

    @abstractmethod
    def read_file(
        self, file_name: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO:
        """
        Read the content of a given file by the name

        Parameters:
        - file_name: Name of file to read
        - mode: Mode to open the file (e.g. 'b' for binary)
        - use_tempfile: Whether to use a temporary file to store the contents
                        in order to avoid loading the entire file into memory

        Returns:
            Contents of the file and metadata dict
        """

    @abstractmethod
    def read_file_record(self, file_name: str) -> PGFileStore:
        """
        Read the file record by the name
        """

    @abstractmethod
    def delete_file(self, file_name: str) -> None:
        """
        Delete a file by its name.

        Parameters:
        - file_name: Name of file to delete
        """


class PostgresBackedFileStore(FileStore):
    def __init__(self, db_session: Session):
        self.db_session = db_session

    def has_file(
        self,
        file_name: str,
        file_origin: FileOrigin,
        file_type: str,
        display_name: str | None = None,
    ) -> bool:
        file_record = get_pgfilestore_by_file_name_optional(
            file_name=display_name or file_name, db_session=self.db_session
        )
        return (
            file_record is not None
            and file_record.file_origin == file_origin
            and file_record.file_type == file_type
        )

    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict | None = None,
        commit: bool = True,
    ) -> None:
        try:
            # The large objects in postgres are saved as special objects can be listed with
            # SELECT * FROM pg_largeobject_metadata;
            obj_id = create_populate_lobj(content=content, db_session=self.db_session)
            upsert_pgfilestore(
                file_name=file_name,
                display_name=display_name or file_name,
                file_origin=file_origin,
                file_type=file_type,
                lobj_oid=obj_id,
                db_session=self.db_session,
                file_metadata=file_metadata,
            )
            if commit:
                self.db_session.commit()
        except Exception:
            self.db_session.rollback()
            raise

    def read_file(
        self, file_name: str, mode: str | None = None, use_tempfile: bool = False
    ) -> IO:
        file_record = get_pgfilestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )
        return read_lobj(
            lobj_oid=file_record.lobj_oid,
            db_session=self.db_session,
            mode=mode,
            use_tempfile=use_tempfile,
        )

    def read_file_record(self, file_name: str) -> PGFileStore:
        file_record = get_pgfilestore_by_file_name(
            file_name=file_name, db_session=self.db_session
        )

        return file_record

    def delete_file(self, file_name: str) -> None:
        try:
            file_record = get_pgfilestore_by_file_name(
                file_name=file_name, db_session=self.db_session
            )
            delete_lobj_by_id(file_record.lobj_oid, db_session=self.db_session)
            delete_pgfilestore_by_file_name(
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


def get_default_file_store(db_session: Session) -> FileStore:
    # The only supported file store now is the Postgres File Store
    return PostgresBackedFileStore(db_session=db_session)
