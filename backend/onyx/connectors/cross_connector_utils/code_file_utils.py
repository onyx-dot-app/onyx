"""Shared helpers for connectors that index source-code files.

The document-metadata contract these connectors write (`CODE_FILE_*` keys)
lives in `onyx.configs.constants`, so retrieval can read it without importing
from `connectors`.
"""

from fnmatch import fnmatch
from pathlib import PurePosixPath

# Grammars for text formats that commonly hold credentials (.env, .pem).
# Never indexed, regardless of connector settings.
SENSITIVE_FILE_LANGUAGES = frozenset({"dotenv", "pem"})

# The grammar detector keys off the final extension, so it misses the names
# secrets are stored under: `.env.local` and key files resolve to no grammar
# at all. Match the basename, which is what the convention is about.
SENSITIVE_FILE_PATTERNS = (
    ".env*",
    "*.env",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.ppk",
    "*_rsa",
    "*_ed25519",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    "credentials",
    "*.kdbx",
)

# Grammars the image build extracts ahead of time. Anything outside this set
# still extracts on demand from the same bundle. Names are checked against the
# pack's manifest by a unit test.
DEFAULT_CODE_GRAMMARS = (
    "bash",
    "c",
    "cpp",
    "csharp",
    "css",
    "dockerfile",
    "go",
    "gomod",
    "graphql",
    "hcl",
    "html",
    "ini",
    "java",
    "javascript",
    "json",
    "kotlin",
    "lua",
    "make",
    "markdown",
    "php",
    "powershell",
    "proto",
    "python",
    "ruby",
    "rust",
    "scala",
    "scss",
    "sql",
    "swift",
    "terraform",
    "toml",
    "tsx",
    "typescript",
    "xml",
    "yaml",
)


def infer_code_language(file_path: str | None) -> str | None:
    """Grammar name for a path, from tree-sitter-language-pack's extension
    registry. None when the path is empty or the extension is unknown.

    A grammar lookup, not a code-vs-prose judgment: prose formats with
    grammars (e.g. .md -> markdown) return that grammar. Callers decide what
    to exclude — connectors subtract their own document extensions, and both
    connectors and the chunker call `is_sensitive_code_file` themselves.
    """
    if not file_path:
        return None
    # Local import: keeps the language pack off the connector import path.
    from tree_sitter_language_pack import detect_language_from_path

    return detect_language_from_path(file_path)


def is_sensitive_code_file(file_path: str | None) -> bool:
    """True when the path names a file that conventionally holds credentials.

    Checked at the chunker as well as in connectors, so directly-ingested
    CodeSections cannot bypass the exclusion via a supplied ``language``.
    Matches the basename against SENSITIVE_FILE_PATTERNS, then falls back to
    the grammar detector for formats it recognises by extension.
    """
    if not file_path:
        return False
    basename = PurePosixPath(file_path.replace("\\", "/")).name.lower()
    if any(fnmatch(basename, pattern) for pattern in SENSITIVE_FILE_PATTERNS):
        return True
    return infer_code_language(file_path) in SENSITIVE_FILE_LANGUAGES
