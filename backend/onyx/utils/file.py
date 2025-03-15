from typing import cast

import puremagic
from pydantic import BaseModel


class OnyxFile(BaseModel):
    data: bytes
    mime_type: str


class OnyxStaticFileManager:
    @staticmethod
    def get_static(filename: str) -> OnyxFile | None:
        try:
            mime_type: str = "application/octet-stream"
            with open(filename, "rb") as f:
                file_content = f.read()
                matches = puremagic.magic_string(file_content)
                if matches:
                    mime_type = cast(str, matches[0].mime_type)
        except (OSError, FileNotFoundError, PermissionError):
            return None

        return OnyxFile(data=file_content, mime_type=mime_type)
