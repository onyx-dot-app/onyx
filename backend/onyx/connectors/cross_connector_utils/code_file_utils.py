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

# Machine-written files: build output and dependency lock files. They are
# large, they dominate a repo's file count, and they are noise in retrieval.
#
# Hand-maintained because no authoritative list ships as a Python package.
# GitHub's own answer is linguist (`vendor.yml` plus `generated.rb`), which is
# Ruby, has no maintained port, and would have to be vendored and translated.
# The naming conventions below have been stable for years, so the list is
# short and rarely moves; extend it rather than reaching for a dependency.
GENERATED_FILE_PATTERNS = (
    "*.min.*",
    "*.lock",
    "*-lock.json",
    "*-lock.yaml",
    "*.lockb",
    "*.pb.go",
    "*.pb.cc",
    "*.pb.h",
    "*_pb2.py",
    "*_pb2_grpc.py",
)

# Formats the pack has grammars for but that are not code: .txt resolves to
# the Vim help-file grammar, and .csv/.tsv have a TabularSection path.
NON_CODE_LANGUAGES = frozenset({"vimdoc", "rst", "csv", "tsv"})


# The pack's registry is extension-only, so these resolve to nothing.
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

    The prose and tabular grammars in NON_CODE_LANGUAGES are subtracted, so
    the answer is a code language. Everything else is a grammar lookup rather
    than a code-vs-prose judgment: markdown has a grammar and returns it, so
    connectors that keep prose out of code indexing still subtract their own
    document extensions (e.g. the GitHub connector's docs set). Whether the
    file holds credentials is a separate question — ask
    `is_sensitive_code_file`.
    """
    if not file_path:
        return None
    basename = PurePosixPath(file_path.replace("\\", "/")).name.lower()
    known = BASENAME_LANGUAGES.get(basename)
    if known is not None:
        return known
    if basename.startswith("dockerfile."):
        return "dockerfile"
    # Local import: keeps the language pack off the connector import path.
    from tree_sitter_language_pack import detect_language_from_path

    language = detect_language_from_path(file_path)
    return None if language in NON_CODE_LANGUAGES else language


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


def is_generated_code_file(file_path: str | None) -> bool:
    """True when the path names build output or a dependency lock file.

    Separate from language inference: a lock file has a perfectly good
    grammar, it is just not worth indexing.
    """
    if not file_path:
        return False
    basename = PurePosixPath(file_path.replace("\\", "/")).name.lower()
    return any(fnmatch(basename, pattern) for pattern in GENERATED_FILE_PATTERNS)
