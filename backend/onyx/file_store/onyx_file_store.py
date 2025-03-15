from typing import cast

import puremagic

from onyx.file_store.file_store import PostgresBackedFileStore
from onyx.utils.file import OnyxFile


class OnyxFileStore(PostgresBackedFileStore):
    def get_onyx_file(self, filename: str) -> OnyxFile | None:
        mime_type: str = "application/octet-stream"
        try:
            file_io = self.read_file(filename, mode="b")
            file_content = file_io.read()
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)
            return OnyxFile(data=file_content, mime_type=mime_type)
        except Exception:
            return None
