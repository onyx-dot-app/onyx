from onyx.file_store.models import ChatFileType
from onyx.utils.file_types import UploadMimeTypes


def mime_type_to_chat_file_type(mime_type: str | None) -> ChatFileType:
    if mime_type is None:
        return ChatFileType.PLAIN_TEXT

    if mime_type in UploadMimeTypes.IMAGE_MIME_TYPES:
        return ChatFileType.IMAGE

    if mime_type in UploadMimeTypes.CSV_MIME_TYPES:
        return ChatFileType.CSV

    if mime_type in UploadMimeTypes.DOCUMENT_MIME_TYPES:
        return ChatFileType.DOC

    return ChatFileType.PLAIN_TEXT
