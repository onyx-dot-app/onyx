import io

from PIL import Image

from onyx.configs.constants import ONYX_EMAILABLE_LOGO_MAX_DIM
from onyx.db.engine import get_session_with_shared_schema
from onyx.file_store.file_store import PostgresBackedFileStore
from onyx.utils.file import FileWithMimeType
from onyx.utils.file import OnyxStaticFileManager
from onyx.utils.variable_functionality import (
    fetch_ee_implementation_or_noop,
)


class OnyxRuntime:
    """Used by the application to get the final runtime value of a setting.

    Rationale: Settings and overrides may be persisted in multiple places, including the
    DB, Redis, env vars, and default constants, etc. The logic to present a final
    setting to the application should be centralized and in one place.

    Example: To get the logo for the application, one must check the DB for an override,
    use the override if present, fall back to the filesystem if not present, and worry
    about enterprise or not enterprise.
    """

    @staticmethod
    def _get_with_static_fallback(
        db_filename: str | None, static_filename: str
    ) -> FileWithMimeType:
        onyx_file: FileWithMimeType | None = None

        if db_filename:
            with get_session_with_shared_schema() as db_session:
                file_store = PostgresBackedFileStore(db_session)
                onyx_file = file_store.get_file_with_mime_type(db_filename)

        if not onyx_file:
            onyx_file = OnyxStaticFileManager.get_static(static_filename)

        if not onyx_file:
            raise RuntimeError(
                f"Resource not found: db={db_filename} static={static_filename}"
            )

        return onyx_file

    @staticmethod
    def get_logo() -> FileWithMimeType:
        STATIC_FILENAME = "static/images/logo.png"

        db_filename: str | None = fetch_ee_implementation_or_noop(
            "onyx.server.enterprise_settings.store", "get_logo_filename", None
        )

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)

    @staticmethod
    def get_emailable_logo() -> FileWithMimeType:
        onyx_file = OnyxRuntime.get_logo()

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
            onyx_file = FileWithMimeType(
                data=output_buffer.getvalue(), mime_type="image/png"
            )

        return onyx_file

    @staticmethod
    def get_logotype() -> FileWithMimeType:
        STATIC_FILENAME = "static/images/logotype.png"

        db_filename: str | None = fetch_ee_implementation_or_noop(
            "onyx.server.enterprise_settings.store", "get_logotype_filename", None
        )

        return OnyxRuntime._get_with_static_fallback(db_filename, STATIC_FILENAME)
