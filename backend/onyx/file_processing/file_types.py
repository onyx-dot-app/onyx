import mimetypes
import os
from pathlib import Path

PRESENTATION_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

SPREADSHEET_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
# Macro-enabled Excel workbooks (.xlsm) — parseable by openpyxl just like xlsx.
# Stored lowercase; chat MIME classification normalizes to lowercase before
# membership checks.
SPREADSHEET_MACRO_MIME_TYPE = "application/vnd.ms-excel.sheet.macroenabled.12"
SPREADSHEET_MIME_TYPES = {SPREADSHEET_MIME_TYPE, SPREADSHEET_MACRO_MIME_TYPE}
WORD_PROCESSING_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PDF_MIME_TYPE = "application/pdf"
PLAIN_TEXT_MIME_TYPE = "text/plain"

# Server images lack /etc/mime.types, so mimetypes cannot resolve Office files.
_OFFICE_MIME_TYPES_BY_EXTENSION: dict[str, str] = {
    ".xlsx": SPREADSHEET_MIME_TYPE,
    ".xlsm": SPREADSHEET_MACRO_MIME_TYPE,
    ".docx": WORD_PROCESSING_MIME_TYPE,
    ".pptx": PRESENTATION_MIME_TYPE,
}


def guess_mime_type(filename: str) -> str | None:
    extension = os.path.splitext(filename)[1].lower()
    return (
        _OFFICE_MIME_TYPES_BY_EXTENSION.get(extension)
        or mimetypes.guess_type(filename)[0]
    )


class OnyxMimeTypes:
    IMAGE_MIME_TYPES = {"image/jpg", "image/jpeg", "image/png", "image/webp"}
    CSV_MIME_TYPES = {"text/csv"}
    TABULAR_MIME_TYPES = CSV_MIME_TYPES | SPREADSHEET_MIME_TYPES
    TEXT_MIME_TYPES = {
        PLAIN_TEXT_MIME_TYPE,
        "text/markdown",
        "text/x-markdown",
        "text/x-log",
        "text/x-config",
        "text/tab-separated-values",
        "application/json",
        "application/xml",
        "text/xml",
        "application/x-yaml",
        "application/yaml",
        "text/yaml",
        "text/x-yaml",
    }
    DOCUMENT_MIME_TYPES = {
        PDF_MIME_TYPE,
        WORD_PROCESSING_MIME_TYPE,
        PRESENTATION_MIME_TYPE,
        "message/rfc822",
        "application/epub+zip",
    }

    # Agent and project files whose original bytes go to the Python tool.
    CODE_INTERPRETER_STAGED_MIME_TYPES = TABULAR_MIME_TYPES | {
        WORD_PROCESSING_MIME_TYPE,
        PRESENTATION_MIME_TYPE,
    }

    ALLOWED_MIME_TYPES = IMAGE_MIME_TYPES.union(
        TEXT_MIME_TYPES, DOCUMENT_MIME_TYPES, TABULAR_MIME_TYPES
    )

    EXCLUDED_IMAGE_TYPES = {
        "image/bmp",
        "image/tiff",
        "image/gif",
        "image/svg+xml",
        "image/avif",
    }


class OnyxFileExtensions:
    SPREADSHEET_EXTENSIONS = {
        ".xlsx",
        ".xlsm",
    }
    TABULAR_EXTENSIONS = {
        ".csv",
        ".tsv",
    } | SPREADSHEET_EXTENSIONS
    PLAIN_TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".mdx",
        ".conf",
        ".log",
        ".json",
        ".csv",
        ".tsv",
        ".xml",
        ".yml",
        ".yaml",
        ".sql",
    }
    DOCUMENT_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".pptx",
        ".eml",
        ".epub",
        ".html",
    } | SPREADSHEET_EXTENSIONS
    IMAGE_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    TEXT_AND_DOCUMENT_EXTENSIONS = PLAIN_TEXT_EXTENSIONS.union(DOCUMENT_EXTENSIONS)

    ALL_ALLOWED_EXTENSIONS = TEXT_AND_DOCUMENT_EXTENSIONS.union(IMAGE_EXTENSIONS)


def get_file_ext(file_path_or_name: str | Path) -> str:
    _, extension = os.path.splitext(file_path_or_name)
    return extension.lower()


def is_indexable_file_type(
    file_name: str, mime_type: str | None, allow_images: bool
) -> bool:
    """True when Onyx can read content from a file of this name and type.

    An image (by a supported image mime type or extension) needs
    ``allow_images``. Any other file needs a supported text or document
    extension, because text extraction selects its parser by extension. A
    connector that reads some mime types with its own code checks those types
    before it calls this function."""
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    extension = get_file_ext(file_name)
    if (
        mime in OnyxMimeTypes.IMAGE_MIME_TYPES
        or extension in OnyxFileExtensions.IMAGE_EXTENSIONS
    ):
        return allow_images
    return extension in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
