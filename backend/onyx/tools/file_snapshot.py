"""File references and local contents retained by execution checkpoints."""

from pydantic import BaseModel, ConfigDict

from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.tools.models import ChatFile


class SavedChatFile(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")
    filename: str
    content: bytes | None = None
    file_id: str | None = None

    @classmethod
    def capture(cls, file: ChatFile) -> "SavedChatFile":
        return cls(
            filename=file.filename,
            file_id=file.file_id,
            content=None if file.file_id else file.content,
        )

    def restore(self) -> ChatFile:
        if self.file_id is not None:
            file_id = self.file_id
            return ChatFile.lazy_from_filename(
                filename=self.filename,
                file_id=file_id,
                loader=lambda: read_checkpoint_file(file_id),
            )
        if self.content is None:
            raise ValueError(
                "Checkpoint file has neither content nor a stored reference"
            )
        return ChatFile(filename=self.filename, content=self.content)


class SavedLoadedFile(BaseModel):
    file_id: str
    file_type: ChatFileType
    filename: str | None
    content_text: str | None
    token_count: int
    content_pending: bool

    @classmethod
    def capture(cls, file: ChatLoadedFile) -> "SavedLoadedFile":
        return cls(
            file_id=file.file_id,
            file_type=file.file_type,
            filename=file.filename,
            content_text=file.content_text,
            token_count=file.token_count,
            content_pending=file.content_pending,
        )

    def restore(self) -> ChatLoadedFile:
        return ChatLoadedFile.lazy_loaded(
            file_id=self.file_id,
            loader=lambda: read_checkpoint_file(self.file_id),
            file_type=self.file_type,
            filename=self.filename,
            content_text=self.content_text,
            token_count=self.token_count,
            content_pending=self.content_pending,
        )


class SavedContextFiles(BaseModel):
    """Keep ordinary file metadata separate from binary image contents."""

    context: ExtractedContextFiles
    images: list[SavedLoadedFile]

    @classmethod
    def capture(cls, files: ExtractedContextFiles) -> "SavedContextFiles":
        return cls(
            context=files.model_copy(update={"image_files": []}, deep=True),
            images=[SavedLoadedFile.capture(file) for file in files.image_files],
        )

    def restore(self) -> ExtractedContextFiles:
        return self.context.model_copy(
            update={"image_files": [file.restore() for file in self.images]}, deep=True
        )


def read_checkpoint_file(file_id: str) -> bytes:
    with get_default_file_store().read_file(file_id, mode="b") as content:
        return content.read()
