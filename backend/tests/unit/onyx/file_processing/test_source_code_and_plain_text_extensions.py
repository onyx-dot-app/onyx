from collections.abc import Generator
from io import BytesIO
from unittest.mock import patch

import pytest

from onyx.connectors.file.connector import _process_file
from onyx.file_processing.extract_file_text import extract_text_and_images
from onyx.file_processing.file_types import (
    OnyxFileExtensions,
    guess_mime_type,
    is_indexable_file_type,
    load_configured_plain_text_extensions,
)


@pytest.fixture(autouse=True)
def mock_unstructured_api_key() -> Generator[None, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


def test_sandbox_only_extensions_remain_disjoint_from_default_plain_text() -> None:
    assert not (
        OnyxFileExtensions.SANDBOX_ONLY_EXTENSIONS
        & OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
    )
    assert ".markdown" in OnyxFileExtensions.BASE_PLAIN_TEXT_EXTENSIONS
    assert ".markdown" in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS


def test_env_var_plain_text_file_extensions_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orig_plain = OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS
    orig_text_and_doc = OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS
    orig_all_allowed = OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS

    try:
        monkeypatch.setenv("PLAIN_TEXT_FILE_EXTENSIONS", "zig, .sol, PROTO")
        monkeypatch.setenv("EXTRA_PLAIN_TEXT_FILE_EXTENSIONS", ".v, Nim ")

        loaded = load_configured_plain_text_extensions()
        assert ".zig" in loaded
        assert ".sol" in loaded
        assert ".proto" in loaded
        assert ".v" in loaded
        assert ".nim" in loaded

        OnyxFileExtensions.reload_configured_extensions()
        assert ".zig" in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS
        assert ".zig" in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS
        assert is_indexable_file_type("main.zig", None, allow_images=True) is True
        assert ".sol" in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS
        assert ".v" in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS

        monkeypatch.delenv("PLAIN_TEXT_FILE_EXTENSIONS", raising=False)
        monkeypatch.delenv("EXTRA_PLAIN_TEXT_FILE_EXTENSIONS", raising=False)
        OnyxFileExtensions.reload_configured_extensions()
        assert ".zig" not in OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS
        assert is_indexable_file_type("main.zig", None, allow_images=True) is False
    finally:
        OnyxFileExtensions.PLAIN_TEXT_EXTENSIONS = orig_plain
        OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS = orig_text_and_doc
        OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS = orig_all_allowed


def test_extract_text_and_images_code_files() -> None:
    py_code = (
        b"def calculate_total(items):\n    return sum(item.price for item in items)\n"
    )
    res_py = extract_text_and_images(BytesIO(py_code), "templater.py")
    assert "def calculate_total" in res_py.text_content
    assert res_py.embedded_images == []

    java_code = (
        b"public class Greeter {\n    public static void main(String[] args) {}\n}\n"
    )
    res_java = extract_text_and_images(BytesIO(java_code), "Greeter.java")
    assert "public class Greeter" in res_java.text_content
    assert res_java.embedded_images == []


def test_extract_text_and_images_unknown_extension_plain_text_fallback() -> None:
    custom_text = b"SET VARIABLE = 42\nRUN COMMAND\n"
    res = extract_text_and_images(BytesIO(custom_text), "config.unknownformat")
    assert "SET VARIABLE = 42" in res.text_content


def test_file_to_document_with_source_code_and_fallback() -> None:
    py_bytes = b"print('hello world')\n"
    docs_py = _process_file(
        file_id="file_1",
        file_name="main.py",
        file=BytesIO(py_bytes),
        metadata={},
        pdf_pass=None,
        file_type=None,
        stage=None,
    )
    assert len(docs_py) == 1
    assert docs_py[0].sections[0].text == "print('hello world')"

    java_bytes = b"package com.example;\nclass App {}\n"
    docs_java = _process_file(
        file_id="file_2",
        file_name="App.java",
        file=BytesIO(java_bytes),
        metadata={},
        pdf_pass=None,
        file_type=None,
        stage=None,
    )
    assert len(docs_java) == 1
    assert docs_java[0].sections[0].text is not None
    assert "package com.example;" in docs_java[0].sections[0].text

    # Unrecognized extension with valid plain text content
    unknown_text_bytes = b"rule custom_rule { condition: true }\n"
    docs_unknown = _process_file(
        file_id="file_3",
        file_name="rules.customext",
        file=BytesIO(unknown_text_bytes),
        metadata={},
        pdf_pass=None,
        file_type=None,
        stage=None,
    )
    assert len(docs_unknown) == 1
    assert docs_unknown[0].sections[0].text is not None
    assert "rule custom_rule" in docs_unknown[0].sections[0].text

    # Unrecognized extension with binary content should be rejected
    binary_bytes = b"\x00\x01\x02\x03\xff\xfe\x00\x00\x12\x34"
    docs_binary = _process_file(
        file_id="file_4",
        file_name="firmware.customext",
        file=BytesIO(binary_bytes),
        metadata={},
        pdf_pass=None,
        file_type=None,
        stage=None,
    )
    assert docs_binary == []


def test_guess_mime_type_for_code_extensions() -> None:
    # Ensure .ts does not resolve to video/mp2t
    assert guess_mime_type("index.ts") == "text/plain"
    assert guess_mime_type("Component.tsx") == "text/plain"
    # Ensure .rs does not resolve to application/rls-services+xml
    assert guess_mime_type("main.rs") == "text/plain"
    assert guess_mime_type("script.py") == "text/x-python"
    assert guess_mime_type("Server.java") == "text/x-java-source"
