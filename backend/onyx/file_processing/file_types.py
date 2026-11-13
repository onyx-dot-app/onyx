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

_CODE_MIME_TYPES_BY_EXTENSION: dict[str, str] = {
    ".ts": "text/plain",
    ".tsx": "text/plain",
    ".rs": "text/plain",
    ".py": "text/x-python",
    ".java": "text/x-java-source",
    ".kt": "text/plain",
    ".kts": "text/plain",
    ".go": "text/plain",
    ".cs": "text/plain",
    ".cpp": "text/plain",
    ".c": "text/plain",
    ".h": "text/plain",
    ".hpp": "text/plain",
    ".sh": "text/x-sh",
    ".bash": "text/x-sh",
    ".zsh": "text/x-sh",
    ".rb": "text/plain",
    ".php": "text/plain",
    ".swift": "text/plain",
    ".scala": "text/plain",
    ".r": "text/plain",
    ".lua": "text/plain",
    ".sql": "text/plain",
    ".md": "text/markdown",
    ".mdx": "text/markdown",
    ".markdown": "text/markdown",
    ".toml": "text/plain",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".json": "application/json",
    ".xml": "application/xml",
}

_CUSTOM_MIME_TYPES_BY_EXTENSION: dict[str, str] = {
    **_OFFICE_MIME_TYPES_BY_EXTENSION,
    **_CODE_MIME_TYPES_BY_EXTENSION,
}


def guess_mime_type(filename: str) -> str | None:
    extension = os.path.splitext(filename)[1].lower()
    return (
        _CUSTOM_MIME_TYPES_BY_EXTENSION.get(extension)
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
        "text/x-python",
        "text/x-java-source",
        "text/x-java",
        "text/x-c",
        "text/x-c++",
        "text/javascript",
        "application/javascript",
        "text/typescript",
        "application/typescript",
        "text/x-sh",
        "text/x-ruby",
        "text/x-go",
        "text/x-rust",
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


def load_configured_plain_text_extensions() -> set[str]:
    """Parse comma-separated file extensions configured via environment variables.

    Supports both PLAIN_TEXT_FILE_EXTENSIONS and EXTRA_PLAIN_TEXT_FILE_EXTENSIONS.
    """
    extensions: set[str] = set()
    for env_var in ("PLAIN_TEXT_FILE_EXTENSIONS", "EXTRA_PLAIN_TEXT_FILE_EXTENSIONS"):
        val = os.environ.get(env_var, "")
        if val.strip():
            for item in val.split(","):
                cleaned = item.strip().lower()
                if cleaned:
                    if not cleaned.startswith("."):
                        cleaned = f".{cleaned}"
                    extensions.add(cleaned)
    return extensions


class OnyxFileExtensions:
    SPREADSHEET_EXTENSIONS = {
        ".xlsx",
        ".xlsm",
    }
    TABULAR_EXTENSIONS = {
        ".csv",
        ".tsv",
    } | SPREADSHEET_EXTENSIONS
    BASE_PLAIN_TEXT_EXTENSIONS = {
        ".txt",
        ".md",
        ".mdx",
        ".markdown",
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
    CODE_EXTENSIONS = {
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".kt",
        ".kts",
        ".py",
        ".pyw",
        ".rb",
        ".rs",
        ".scala",
        ".swift",
        ".php",
        ".sh",
        ".bash",
        ".zsh",
        ".bat",
        ".ps1",
        ".r",
        ".lua",
        ".pl",
        ".m",
        ".mm",
        ".vue",
        ".svelte",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".toml",
        ".ini",
        ".env",
        ".proto",
        ".graphql",
        ".dockerfile",
    }
    PLAIN_TEXT_EXTENSIONS = (
        BASE_PLAIN_TEXT_EXTENSIONS
        | CODE_EXTENSIONS
        | load_configured_plain_text_extensions()
    )
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

    @classmethod
    def reload_configured_extensions(cls) -> None:
        """Reload plain-text extensions when environment variables change."""
        cls.PLAIN_TEXT_EXTENSIONS = (
            cls.BASE_PLAIN_TEXT_EXTENSIONS
            | cls.CODE_EXTENSIONS
            | load_configured_plain_text_extensions()
        )
        cls.TEXT_AND_DOCUMENT_EXTENSIONS = cls.PLAIN_TEXT_EXTENSIONS.union(
            cls.DOCUMENT_EXTENSIONS
        )
        cls.ALL_ALLOWED_EXTENSIONS = cls.TEXT_AND_DOCUMENT_EXTENSIONS.union(
            cls.IMAGE_EXTENSIONS
        )
