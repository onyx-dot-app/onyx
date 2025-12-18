PRESENTATION_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

SPREADSHEET_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
WORD_PROCESSING_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PDF_MIME_TYPE = "application/pdf"
PLAIN_TEXT_MIME_TYPE = "text/plain"


class OnyxMimeTypes:
    IMAGE_MIME_TYPES = {"image/jpg", "image/jpeg", "image/png", "image/webp"}
    CSV_MIME_TYPES = {"text/csv"}
    TEXT_MIME_TYPES = {
        PLAIN_TEXT_MIME_TYPE,
        "text/markdown",
        "text/x-markdown",
        "text/x-config",
        "text/tab-separated-values",
        "application/json",
        "application/xml",
        "text/xml",
        "application/x-yaml",
    }
    DOCUMENT_MIME_TYPES = {
        PDF_MIME_TYPE,
        WORD_PROCESSING_MIME_TYPE,
        PRESENTATION_MIME_TYPE,
        SPREADSHEET_MIME_TYPE,
        "message/rfc822",
        "application/epub+zip",
    }

    ALLOWED_MIME_TYPES = IMAGE_MIME_TYPES.union(
        TEXT_MIME_TYPES, DOCUMENT_MIME_TYPES, CSV_MIME_TYPES
    )

    EXCLUDED_IMAGE_TYPES = {
        "image/bmp",
        "image/tiff",
        "image/gif",
        "image/svg+xml",
        "image/avif",
    }


class OnyxFileExtensions:
    PLAIN_TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".mdx",
        ".conf",
        ".log",
        "json",
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
        ".xlsx",
        ".eml",
        ".epub",
        ".html",
    }
    IMAGE_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    TEXT_AND_DOCUMENT_EXTENSIONS = PLAIN_TEXT_EXTENSIONS.union(DOCUMENT_EXTENSIONS)

    ALL_ALLOWED_EXTENSIONS = TEXT_AND_DOCUMENT_EXTENSIONS.union(IMAGE_EXTENSIONS)
