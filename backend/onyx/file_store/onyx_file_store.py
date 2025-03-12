import magic

from onyx.file_store.file_store import PostgresBackedFileStore
from onyx.utils.file import OnyxFile


class OnyxFileStore(PostgresBackedFileStore):
    def get_static_image(self, filename: str) -> OnyxFile:
        file_io = self.read_file(filename, mode="b")
        file_content = file_io.read()
        mime_type = magic.Magic(mime=True).from_buffer(file_content)
        return OnyxFile(data=file_content, mime_type=mime_type)

    def get_db_image(self, filename: str) -> OnyxFile:
        file_io = self.read_file(filename, mode="b")
        file_content = file_io.read()
        mime_type = magic.Magic(mime=True).from_buffer(file_content)
        return OnyxFile(data=file_content, mime_type=mime_type)

    def get_logo(self) -> OnyxFile:
        return self.get_static_image("static/images/logo.png")

    def get_logotype(self) -> OnyxFile:
        return self.get_static_image("static/images/logotype.png")
