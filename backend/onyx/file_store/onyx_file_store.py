from typing import cast

import puremagic

from onyx.file_store.file_store import PostgresBackedFileStore
from onyx.utils.file import OnyxFile


class OnyxFileStore(PostgresBackedFileStore):
    def get_static_image(self, filename: str) -> OnyxFile:
        mime_type: str = "application/octet-stream"
        with open(filename, "b") as f:
            file_content = f.read()
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)

        return OnyxFile(data=file_content, mime_type=mime_type)

    def get_db_image(self, filename: str) -> OnyxFile:
        mime_type: str = "application/octet-stream"
        file_io = self.read_file(filename, mode="b")
        file_content = file_io.read()
        matches = puremagic.magic_string(file_content)
        if matches:
            mime_type = cast(str, matches[0].mime_type)
        return OnyxFile(data=file_content, mime_type=mime_type)

    def get_logo(self) -> OnyxFile:
        return self.get_static_image("static/images/logo.png")

    def get_logotype(self) -> OnyxFile:
        return self.get_static_image("static/images/logotype.png")
