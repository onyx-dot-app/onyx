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

# Grammars the pack resolves for prose and tabular formats. They parse, but
# their chunk boundaries mean nothing for retrieval, and .csv/.tsv have a
# TabularSection path built for them. Subtracted so each connector does not
# have to rediscover that .txt resolves to the Vim help-file grammar.
NON_CODE_LANGUAGES = frozenset({"vimdoc", "rst", "csv", "tsv"})


# The pack's registry is extension-only, so the canonical extensionless names
# resolve to nothing even though their grammars ship with it.
BASENAME_LANGUAGES = {
    "makefile": "make",
    "gnumakefile": "make",
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "cmakelists.txt": "cmake",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "brewfile": "ruby",
}


def infer_code_language(file_path: str | None) -> str | None:
    """Grammar name for a path, from tree-sitter-language-pack's extension
    registry plus the extensionless names it does not cover. None when the
    path is empty or nothing matches.

    A grammar lookup, not a code-vs-prose judgment: prose formats with
    grammars (e.g. .md -> markdown) return that grammar. Callers decide what
    to exclude — they subtract their own document extensions and
    NON_CODE_LANGUAGES, and call `is_sensitive_code_file` themselves.
    """
    if not file_path:
        return None
    basename = PurePosixPath(file_path.replace("\\", "/")).name.lower()
    known = BASENAME_LANGUAGES.get(basename)
    if known is not None:
        return known
    # Dockerfile.dev / Dockerfile.prod and the like.
    if basename.startswith("dockerfile."):
        return "dockerfile"
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
