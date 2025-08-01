import asyncio
from collections.abc import Callable

from fastapi import Request

from onyx.file_store.models import ChatFileType
from onyx.utils.file_types import UploadMimeTypes
from onyx.utils.logger import setup_logger


logger = setup_logger()


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


async def is_connected(request: Request) -> Callable[[], bool]:
    main_loop = asyncio.get_event_loop()

    def is_connected_sync() -> bool:
        future = asyncio.run_coroutine_threadsafe(request.is_disconnected(), main_loop)
        try:
            is_connected = not future.result(timeout=0.05)
            return is_connected
        except asyncio.TimeoutError:
            logger.warning(
                "Asyncio timed out (potentially missed request to stop streaming)"
            )
            return True
        except Exception as e:
            error_msg = str(e)
            logger.critical(
                f"An unexpected error occured with the disconnect check coroutine: {error_msg}"
            )
            return True

    return is_connected_sync
