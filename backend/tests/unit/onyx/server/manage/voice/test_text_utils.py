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


def test_preserves_intraword_underscores_and_lone_asterisks() -> None:
    # Only paired emphasis is stripped; literal delimiters in normal text survive.
    assert strip_markdown_for_tts("call user_id and file_name_here") == (
        "call user_id and file_name_here"
    )
    assert strip_markdown_for_tts("2 * 3 = 6") == "2 * 3 = 6"
    # A lone "5*" next to real italics must not be paired with the italic opener.
    assert strip_markdown_for_tts("Rated 5* overall; see *italics* here") == (
        "Rated 5* overall; see italics here"
    )


def test_converts_links_to_label() -> None:
    assert strip_markdown_for_tts("see [the docs](https://example.com/x)") == (
        "see the docs"
    )


def test_link_url_with_balanced_parens() -> None:
    # URLs containing parentheses must not leak a trailing ")".
    assert (
        strip_markdown_for_tts(
            "[C](https://en.wikipedia.org/wiki/C_(programming_language)) rules"
        )
        == "C rules"
    )


def test_collapses_whitespace_and_trims() -> None:
    assert strip_markdown_for_tts("  hello\n\n   world  ") == "hello world"


def test_drops_fenced_code_blocks() -> None:
    # Reading a code block aloud is noise; keep the surrounding prose only.
    assert strip_markdown_for_tts("Run this:\n```python\nprint(1)\n```\nDone.") == (
        "Run this: Done."
    )


def test_flattens_lists() -> None:
    assert strip_markdown_for_tts("Steps:\n- first\n- second") == (
        "Steps: first second"
    )


def test_empty_string() -> None:
    assert strip_markdown_for_tts("") == ""
