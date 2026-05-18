from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_store.models import ChatFileType


def _normalize_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def mime_type_to_chat_file_type(mime_type: str | None) -> ChatFileType:
    if mime_type is None:
        return ChatFileType.PLAIN_TEXT

    normalized_mime_type = _normalize_mime_type(mime_type)
    if normalized_mime_type in OnyxMimeTypes.IMAGE_MIME_TYPES:
        return ChatFileType.IMAGE

    if normalized_mime_type in OnyxMimeTypes.TABULAR_MIME_TYPES:
        return ChatFileType.TABULAR

    if normalized_mime_type in OnyxMimeTypes.DOCUMENT_MIME_TYPES:
        return ChatFileType.DOC

    return ChatFileType.PLAIN_TEXT
