from pydantic import BaseModel


class EgnyteLockInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""


class EgnyteFile(BaseModel):
    name: str
    path: str
    # Identifies the file across versions. ``entry_id`` names one version.
    group_id: str
    entry_id: str
    # RFC 1123 date, e.g. "Tue, 10 Nov 2026 18:00:00 GMT".
    last_modified: str
    uploaded_by: str | None = None
    lock_info: EgnyteLockInfo | None = None


class EgnyteFolder(BaseModel):
    name: str
    path: str
    folder_id: str


class EgnyteFolderPage(BaseModel):
    """One page of a folder's direct children."""

    folders: list[EgnyteFolder]
    files: list[EgnyteFile]
