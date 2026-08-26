"""Shared helpers for connectors that index source-code files.

The document-metadata contract these connectors write (`CODE_FILE_*` keys)
lives in `onyx.configs.constants`, so retrieval can read it without importing
from `connectors`.
"""

# Grammars for text formats that commonly hold credentials (.env, .pem).
# Never indexed, regardless of connector settings.
SENSITIVE_FILE_LANGUAGES = frozenset({"dotenv", "pem"})


def _detect_language(file_path: str | None) -> str | None:
    """Grammar name for a path, from tree-sitter-language-pack's extension
    registry. None when the path is empty or the extension is unknown."""
    if not file_path:
        return None
    # Local import: keeps the language pack off the connector import path.
    from tree_sitter_language_pack import detect_language_from_path

    return detect_language_from_path(file_path)


def is_sensitive_code_file(file_path: str | None) -> bool:
    """True when the path maps to a credential-holding format (.env, .pem).

    Checked at the chunker as well as in connectors, so directly-ingested
    CodeSections cannot bypass the exclusion via a supplied ``language``.
    """
    return _detect_language(file_path) in SENSITIVE_FILE_LANGUAGES


def infer_code_language(file_path: str | None) -> str | None:
    """Grammar name for a file path — so the name always matches a grammar the
    code chunker can load. Returns None for unknown extensions and credential
    formats.

    This is a grammar lookup, not a code-vs-prose judgment: prose formats
    with grammars (e.g. .md -> markdown) return that grammar. Connectors that
    must keep prose out of code indexing subtract their own document
    extensions (e.g. the GitHub connector's docs set) before calling this.
    """
    language = _detect_language(file_path)
    if language in SENSITIVE_FILE_LANGUAGES:
        return None
    return language
