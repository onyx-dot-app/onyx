import io

from PIL import Image

from onyx.configs.constants import ONYX_EMAILABLE_LOGO_MAX_DIM
from onyx.db.engine import get_session_with_shared_schema
from onyx.file_store.onyx_file_store import OnyxFileStore
from onyx.utils.file import OnyxFile
from onyx.utils.file import OnyxStaticFileManager
from onyx.utils.variable_functionality import (
    fetch_ee_implementation_or_none,
)


class OnyxRuntime:
    @staticmethod
    def _get_with_static_fallback(
        db_filename: str | None, static_filename: str
    ) -> OnyxFile:
        onyx_file: OnyxFile | None = None

        while True:
            if db_filename:
                with get_session_with_shared_schema() as db_session:
                    file_store: OnyxFileStore = OnyxFileStore(db_session)
                    onyx_file = file_store.get_onyx_file(db_filename)

            if onyx_file:
                break

            onyx_file = OnyxStaticFileManager.get_static(static_filename)
            break

        if not onyx_file:
            raise RuntimeError(
                f"Resource not found: db={db_filename} static={static_filename}"
            )

        return onyx_file

    @staticmethod
    def get_logo() -> OnyxFile:
        STATIC_FILENAME = "static/images/logo.png"

        db_filename: str | None = None
        get_logo_filename_fn = fetch_ee_implementation_or_none(
            "onyx.server.enterprise_settings.store", "get_logo_filename"
        )
        if get_logo_filename_fn:
            db_filename = get_logo_filename_fn()

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)

    @staticmethod
    def get_emailable_logo() -> OnyxFile:
        STATIC_FILENAME = "static/images/logo.png"

        db_filename: str | None = None
        get_logo_filename_fn = fetch_ee_implementation_or_none(
            "onyx.server.enterprise_settings.store", "get_logo_filename"
        )
        if get_logo_filename_fn:
            db_filename = get_logo_filename_fn()

        onyx_file = OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)

        # check dimensions and resize downwards if necessary or if not PNG
        image = Image.open(io.BytesIO(onyx_file.data))
        if (
            image.size[0] > ONYX_EMAILABLE_LOGO_MAX_DIM
            or image.size[1] > ONYX_EMAILABLE_LOGO_MAX_DIM
            or image.format != "PNG"
        ):
            image.thumbnail(
                (ONYX_EMAILABLE_LOGO_MAX_DIM, ONYX_EMAILABLE_LOGO_MAX_DIM),
                Image.LANCZOS,
            )  # maintains aspect ratio
            output_buffer = io.BytesIO()
            image.save(output_buffer, format="PNG")
            onyx_file = OnyxFile(data=output_buffer.getvalue(), mime_type="image/png")

        return onyx_file

    @staticmethod
    def get_logotype() -> OnyxFile:
        STATIC_FILENAME = "static/images/logotype.png"

        db_filename: str | None = None
        get_logotype_filename_fn = fetch_ee_implementation_or_none(
            "onyx.server.enterprise_settings.store", "get_logotype_filename"
        )
        if get_logotype_filename_fn:
            db_filename = get_logotype_filename_fn()

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)
