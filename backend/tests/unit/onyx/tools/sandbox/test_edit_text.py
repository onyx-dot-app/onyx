import time

import pytest

from onyx.tools.tool_implementations.sandbox import patch
from onyx.tools.tool_implementations.sandbox.patch import PatchError, edit_text

NOT_FOUND = "String to replace not found in file.\nString: "


def _matches(count: int, old: str) -> str:
    return (
        f"Found {count} matches of the string to replace, but replace_all is "
        "false. To replace all occurrences, set replace_all to true. To replace "
        "only one occurrence, please provide more context to uniquely identify "
        f"the instance.\nString: {old}"
    )


@pytest.mark.parametrize(
    ("original", "old", "new", "replace_all", "expected"),
    [
        pytest.param(
            "a = 1\nb = 2\n", "b = 2", "b = 3", False, "a = 1\nb = 3\n", id="exact"
        ),
        pytest.param("x x x", "x", "y", True, "y y y", id="replace_all"),
        pytest.param(
            "a\r\nb\r\nc\r\n",
            "a\nb",
            "A\nB\nB2",
            False,
            "A\r\nB\r\nB2\r\nc\r\n",
            id="crlf_kept",
        ),
        pytest.param(
            # Unchanged text keeps its own line breaks.
            "a\r\nb\nc\r\n",
            "b\nc",
            "B\nC",
            False,
            "a\r\nB\r\nC\r\n",
            id="mixed_line_breaks_kept",
        ),
        pytest.param(
            "keep\ndrop\nkeep too\n",
            "drop",
            "",
            False,
            "keep\nkeep too\n",
            id="removed_line_takes_its_break",
        ),
        pytest.param(
            # Text removed from inside a line leaves the line break.
            "a = b; x = 1\nc\n",
            "; x = 1",
            "",
            False,
            "a = b\nc\n",
            id="removed_text_keeps_the_break",
        ),
        pytest.param(
            # A match that starts with a line break takes the whole CRLF.
            "a\r\nb\r\n",
            "\nb",
            "B",
            False,
            "aB\r\n",
            id="match_takes_the_whole_crlf",
        ),
        pytest.param(None, "", "new\n", False, "new\n", id="empty_old_creates"),
        pytest.param(" \n", "", "new\n", False, "new\n", id="empty_old_fills_blank"),
    ],
)
def test_edit_text(
    original: str | None, old: str, new: str, replace_all: bool, expected: str
) -> None:
    assert edit_text(original, old, new, replace_all) == expected


@pytest.mark.parametrize(
    ("original", "old", "new", "message"),
    [
        pytest.param("a\n", "b", "c", NOT_FOUND + "b", id="not_found"),
        pytest.param("x x\n", "x", "y", _matches(2, "x"), id="not_unique"),
        pytest.param(
            # Trailing whitespace is text: no match, never a wrong edit.
            "x = 10\n",
            "x = 1 ",
            "x = 2",
            NOT_FOUND + "x = 1 ",
            id="trailing_whitespace_is_exact",
        ),
        pytest.param(
            # Two line breaks never match one CRLF.
            "a\r\nb\r\n",
            "a\n\nb",
            "X",
            NOT_FOUND + "a\n\nb",
            id="crlf_is_one_break",
        ),
        pytest.param(
            "say(“hi”)\n",
            'say("hi")',
            "bye",
            NOT_FOUND + 'say("hi")',
            id="punctuation_is_exact",
        ),
        pytest.param(
            "a\n",
            "a",
            "a",
            "No changes to make: old_string and new_string are exactly the same.",
            id="no_change",
        ),
        pytest.param(None, "a", "b", "File does not exist.", id="missing_file"),
        pytest.param(
            "content\n",
            "",
            "new",
            "Cannot create new file - file already exists.",
            id="empty_old_on_a_file",
        ),
    ],
)
def test_edit_text_errors(
    original: str | None, old: str, new: str, message: str
) -> None:
    with pytest.raises(PatchError) as error:
        edit_text(original, old, new, False)
    assert str(error.value) == message


def test_an_edit_that_would_make_the_file_too_large_fails() -> None:
    original = "a" * 1024
    with pytest.raises(PatchError) as error:
        edit_text(original, "a", "b" * 1024 * 1024, True)
    assert str(error.value).startswith(
        f"The edit would make the file {1024 * 1024 * 1024} bytes, larger than "
        f"{patch.FILE_TOOL_MAX_FILE_BYTES} bytes"
    )


@pytest.mark.parametrize(
    ("original", "old", "new"),
    [
        pytest.param("\n" * 1_000_000, "\n" * 2_000 + "x", "y", id="line_breaks"),
        pytest.param("a" * 1_000_000, "a" * 10_000 + "b", "", id="removal"),
    ],
)
def test_the_search_time_is_linear_in_the_file_size(
    original: str, old: str, new: str
) -> None:
    started = time.monotonic()
    with pytest.raises(PatchError):
        edit_text(original, old, new, False)
    assert time.monotonic() - started < 1
