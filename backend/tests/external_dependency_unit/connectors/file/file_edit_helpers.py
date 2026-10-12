import json
import zipfile
from io import BytesIO
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from onyx.configs.constants import ONYX_METADATA_FILENAME, FileOrigin
from onyx.db.models import ConnectorCredentialPair, FileRecord
from onyx.file_store.constants import STAGED_FOR_CC_PAIR_METADATA_KEY
from onyx.file_store.file_store import get_default_file_store
from onyx.server.documents.connector import upload_files
from onyx.server.documents.file_connector_staging import stage_file_connector_upload
from onyx.server.documents.models import FileUploadResponse


def text_upload(name: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=name,
        headers=Headers({"content-type": "text/plain"}),
    )


def zip_upload(files: dict[str, bytes], metadata: list[dict[str, Any]]) -> UploadFile:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        zf.writestr(ONYX_METADATA_FILENAME, json.dumps(metadata))
    buffer.seek(0)
    return UploadFile(
        file=buffer,
        filename="batch.zip",
        headers=Headers({"content-type": "application/zip"}),
    )


def read_json_file(file_id: str) -> Any:
    return json.loads(get_default_file_store().read_file(file_id, mode="b").read())


class FilePair:
    """A file connector pair with stored files, and the file ids to delete.
    It records staged files too, since a claim removes their staged mark."""

    def __init__(self, pair: ConnectorCredentialPair) -> None:
        self.pair = pair
        self.file_ids: list[str] = []

    def save_current_files(
        self,
        db_session: Session,
        files: dict[str, bytes],
        zip_metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        uploaded = upload_files(
            [text_upload(name, content) for name, content in files.items()],
            FileOrigin.CONNECTOR,
        )
        self.file_ids.extend(uploaded.file_paths)
        config: dict[str, Any] = {
            "file_locations": uploaded.file_paths,
            "file_names": uploaded.file_names,
        }
        if zip_metadata is not None:
            config["zip_metadata_file_id"] = self.save_metadata_file(
                json.dumps(zip_metadata).encode()
            )
        self.pair.connector.connector_specific_config = config
        db_session.commit()
        return uploaded.file_paths

    def stage(
        self, db_session: Session, uploads: list[UploadFile]
    ) -> FileUploadResponse:
        staged = stage_file_connector_upload(db_session, self.pair.id, uploads)
        self.file_ids.extend(staged.file_paths)
        if staged.zip_metadata_file_id is not None:
            self.file_ids.append(staged.zip_metadata_file_id)
        return staged

    def save_metadata_file(self, content: bytes) -> str:
        file_id = get_default_file_store().save_file(
            content=BytesIO(content),
            display_name=ONYX_METADATA_FILENAME,
            file_origin=FileOrigin.CONNECTOR_METADATA,
            file_type="application/json",
        )
        self.file_ids.append(file_id)
        return file_id


def staged_file_ids(db_session: Session, cc_pair_id: int) -> set[str]:
    return set(
        db_session.scalars(
            select(FileRecord.file_id).where(
                FileRecord.file_metadata[STAGED_FOR_CC_PAIR_METADATA_KEY].astext
                == str(cc_pair_id)
            )
        )
    )
