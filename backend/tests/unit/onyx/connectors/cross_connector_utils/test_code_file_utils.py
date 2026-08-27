import pytest
from tree_sitter_language_pack import manifest_languages

from onyx.connectors.cross_connector_utils.code_file_utils import (
    SENSITIVE_FILE_LANGUAGES,
    infer_code_language,
    is_generated_code_file,
    is_sensitive_code_file,
)


def test_sensitive_languages_are_real_grammars() -> None:
    """A pack upgrade that renames a guarded grammar would make its entry
    dead — and credential files would silently start indexing. Fail here."""
    unknown = SENSITIVE_FILE_LANGUAGES - set(manifest_languages())
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


@pytest.mark.parametrize(
    "path,expected",
    [
        ("Makefile", "make"),
        ("GNUmakefile", "make"),
        ("Dockerfile", "dockerfile"),
        ("Dockerfile.dev", "dockerfile"),
        ("Containerfile", "dockerfile"),
        ("CMakeLists.txt", "cmake"),
        ("Gemfile", "ruby"),
        ("deep/dir/Makefile", "make"),
    ],
)
def test_extensionless_code_files_resolve(path: str, expected: str) -> None:
    """The pack's registry is extension-only, so these canonical names —
    which is how repositories actually spell them — resolve to nothing
    without the basename map."""
    assert infer_code_language(path) == expected


@pytest.mark.parametrize(
    "path", ["a.txt", "requirements.txt", "a.csv", "a.tsv", "a.rst"]
)
def test_prose_and_tabular_files_are_not_code(path: str) -> None:
    """.txt resolves to the Vim help-file grammar and .csv/.tsv have their own
    tabular path; chunking them as code produces meaningless boundaries."""
    assert infer_code_language(path) is None


@pytest.mark.parametrize(
    "path",
    [
        "package-lock.json",
        "yarn.lock",
        "Cargo.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "static/jquery.min.js",
        "static/site.min.css",
        "gen/service.pb.go",
        "gen/service_pb2.py",
    ],
)
def test_generated_files_are_refused(path: str) -> None:
    """Machine-written files outnumber source in a repo and add nothing to
    retrieval, so connectors must be able to drop them."""
    assert is_generated_code_file(path) is True


@pytest.mark.parametrize(
    "path", ["main.py", "lockfile_utils.py", "src/minify.js", "protobuf.py", ""]
)
def test_handwritten_files_are_not_generated(path: str) -> None:
    assert is_generated_code_file(path) is False
