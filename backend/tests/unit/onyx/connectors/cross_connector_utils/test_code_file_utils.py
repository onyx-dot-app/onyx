import pytest
from tree_sitter_language_pack import manifest_languages

from onyx.connectors.cross_connector_utils.code_file_utils import (
    SENSITIVE_FILE_LANGUAGES,
    infer_code_language,
)


def test_sensitive_languages_are_real_grammars() -> None:
    """A pack upgrade that renames a guarded grammar would make its entry
    dead — and credential files would silently start indexing. Fail here."""
    manifest = set(manifest_languages())
    unknown = SENSITIVE_FILE_LANGUAGES - manifest
    assert not unknown, f"Not grammars in tree-sitter-language-pack: {unknown}"


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
        # credential formats are refused
        ("key.pem", None),
        ("secrets.env", None),
        # unknown / not files
        ("image.png", None),
        ("no_extension", None),
        ("", None),
        (None, None),
    ],
)
def test_infer_code_language(path: str | None, expected: str | None) -> None:
    assert infer_code_language(path) == expected
