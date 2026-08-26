import pytest
from tree_sitter_language_pack import manifest_languages

from onyx.connectors.cross_connector_utils.code_file_utils import (
    DEFAULT_CODE_GRAMMARS,
    SENSITIVE_FILE_LANGUAGES,
    infer_code_language,
    is_sensitive_code_file,
)


def test_sensitive_languages_are_real_grammars() -> None:
    """A pack upgrade that renames a guarded grammar would make its entry
    dead — and credential files would silently start indexing. Fail here."""
    manifest = set(manifest_languages())
    unknown = SENSITIVE_FILE_LANGUAGES - manifest
    assert not unknown, f"Not grammars in tree-sitter-language-pack: {unknown}"


def test_default_grammars_are_real_grammars() -> None:
    """A name that is not a grammar is prefetched as a no-op, so the worker
    would still download that language at index time. Fail here instead."""
    manifest = set(manifest_languages())
    unknown = set(DEFAULT_CODE_GRAMMARS) - manifest
    assert not unknown, f"Not grammars in tree-sitter-language-pack: {unknown}"


def test_default_grammars_exclude_credential_formats() -> None:
    """Prefetching a guarded grammar would suggest those files are indexable."""
    assert not set(DEFAULT_CODE_GRAMMARS) & SENSITIVE_FILE_LANGUAGES


@pytest.mark.parametrize(
    "path,expected",
    [
        # source code, named per tree-sitter-language-pack
        ("main.py", "python"),
        ("src/app.tsx", "tsx"),
        ("native/lib.cpp", "cpp"),
        ("Service.cs", "csharp"),
        ("query.sql", "sql"),
        ("deep/nested/mod.rs", "rust"),
        # config / data formats have grammars too
        ("data.json", "json"),
        ("config.yaml", "yaml"),
        # grammar lookup, not a prose judgment — callers subtract doc formats
        ("README.md", "markdown"),
        # a grammar lookup only — refusing credential formats is
        # is_sensitive_code_file's job, and callers ask it separately
        ("key.pem", "pem"),
        ("secrets.env", "dotenv"),
        # unknown / not files
        ("image.png", None),
        ("no_extension", None),
        ("", None),
        (None, None),
    ],
)
def test_infer_code_language(path: str | None, expected: str | None) -> None:
    assert infer_code_language(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        # the grammar detector catches only these two
        ".env",
        "key.pem",
        # ...and misses the names secrets are actually stored under
        ".env.local",
        ".env.production",
        "config/.env.staging",
        "backend/.env.docker",
        "id_rsa",
        "id_ed25519",
        "deploy_rsa",
        "server.key",
        "creds.p12",
        "cert.pfx",
        "store.jks",
        "app.keystore",
        "putty.ppk",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".pgpass",
        "credentials",
        "vault.kdbx",
        # case and separators must not defeat it
        ".ENV.Local",
        "windows\\path\\.env.local",
    ],
)
def test_credential_files_are_refused(path: str) -> None:
    """These hold secrets and must never be chunked, whatever the caller
    supplies as `language`."""
    assert is_sensitive_code_file(path) is True


@pytest.mark.parametrize(
    "path",
    ["main.py", "README.md", "data.json", "src/keyboard.py", "envelope.py", ""],
)
def test_ordinary_files_are_not_refused(path: str) -> None:
    """The patterns must not swallow normal source files."""
    assert is_sensitive_code_file(path) is False
