import mimetypes
import os

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
        # WebVTT. Routed to parse_vtt_transcript rather than read verbatim, but
        # it belongs here so the connectors do not drop it before download.
        ".vtt",
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
