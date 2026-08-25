"""Shared helpers for connectors that index source-code files."""

# Document-metadata `type` value connectors set on source-code file docs.
# Retrieval recognizes code chunks by this alone.
CODE_FILE_METADATA_TYPE = "CodeFile"

# Grammars for text formats that commonly hold credentials (.env, .pem).
# Never indexed, regardless of connector settings.
SENSITIVE_FILE_LANGUAGES = frozenset({"dotenv", "pem"})


def is_sensitive_code_file(file_path: str | None) -> bool:
    """True when the path maps to a credential-holding format (.env, .pem).

    Checked at the chunker as well as in connectors, so directly-ingested
    CodeSections cannot bypass the exclusion via a supplied ``language``.
    """
    if not file_path:
        return False
    # Local import: keeps the language pack off the connector import path.
    from tree_sitter_language_pack import detect_language_from_path

    return detect_language_from_path(file_path) in SENSITIVE_FILE_LANGUAGES


def infer_code_language(file_path: str | None) -> str | None:
    """Grammar name for a file path, from tree-sitter-language-pack's public
    extension registry — so the name always matches a grammar the code
    chunker can load. Returns None for unknown extensions and credential
    formats.

    This is a grammar lookup, not a code-vs-prose judgment: prose formats
    with grammars (e.g. .md -> markdown) return that grammar. Connectors that
    must keep prose out of code indexing subtract their own document
    extensions (e.g. the GitHub connector's docs set) before calling this.
    """
    if not file_path:
        return None
    # Local import: keeps the language pack off the connector import path.
    from tree_sitter_language_pack import detect_language_from_path

    language = detect_language_from_path(file_path)
    if language is None or language in SENSITIVE_FILE_LANGUAGES:
        return None
    return language
