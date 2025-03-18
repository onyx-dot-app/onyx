from typing import cast

import puremagic
from pydantic import BaseModel

from onyx.utils.logger import setup_logger

logger = setup_logger()


class FileWithMimeType(BaseModel):
    data: bytes
    mime_type: str


class OnyxStaticFileManager:
    """Retrieve static resources with this class. Currently, these should all be located
    in the static directory ... e.g. static/images/logo.png"""

    @staticmethod
    def get_static(filename: str) -> FileWithMimeType | None:
        try:
            mime_type: str = "application/octet-stream"
            with open(filename, "rb") as f:
                file_content = f.read()
                matches = puremagic.magic_string(file_content)
                if matches:
                    mime_type = cast(str, matches[0].mime_type)
        except (OSError, FileNotFoundError, PermissionError) as e:
            logger.error(f"Failed to read file {filename}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected exception reading file {filename}: {e}")
            return None

        return FileWithMimeType(data=file_content, mime_type=mime_type)
