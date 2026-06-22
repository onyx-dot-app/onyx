from onyx.server.manage.voice.text_utils import strip_markdown_for_tts


def test_strips_bold_italic_and_code() -> None:
    assert strip_markdown_for_tts("**bold** and *italic* and `code`") == (
        "bold and italic and code"
    )
    assert strip_markdown_for_tts("__bold__ and _italic_") == "bold and italic"


def test_strips_headers_at_line_start() -> None:
    assert strip_markdown_for_tts("# Title\n## Subtitle\nbody") == (
        "Title Subtitle body"
    )


def test_preserves_inline_hash_text() -> None:
    # Hashes not at the start of a line (e.g. "C#", "#1") must be left alone.
    assert strip_markdown_for_tts("C# is great and #1 ranked") == (
        "C# is great and #1 ranked"
    )


def test_converts_links_to_label() -> None:
    assert strip_markdown_for_tts("see [the docs](https://example.com/x)") == (
        "see the docs"
    )


def test_collapses_whitespace_and_trims() -> None:
    assert strip_markdown_for_tts("  hello\n\n   world  ") == "hello world"


def test_empty_string() -> None:
    assert strip_markdown_for_tts("") == ""
