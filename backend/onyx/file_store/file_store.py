from abc import ABC
from abc import abstractmethod
from typing import IO

from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import PGFileStore
from onyx.db.pg_file_store import create_populate_lobj
from onyx.db.pg_file_store import delete_lobj_by_id
from onyx.db.pg_file_store import delete_pgfilestore_by_file_name
from onyx.db.pg_file_store import get_pgfilestore_by_file_name
from onyx.db.pg_file_store import read_lobj
from onyx.db.pg_file_store import upsert_pgfilestore


class FileStore(ABC):
    """
    An abstraction for storing files and large binary objects.
    """

    @abstractmethod
    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict | None = None,
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
        """
        raise NotImplementedError

    @abstractmethod
    def read_file(
        self, file_name: str, mode: str | None, use_tempfile: bool = False
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

    def save_file(
        self,
        file_name: str,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict | None = None,
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


def get_default_file_store(db_session: Session) -> FileStore:
    # The only supported file store now is the Postgres File Store
    return PostgresBackedFileStore(db_session=db_session)
