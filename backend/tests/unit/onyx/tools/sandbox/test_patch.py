import time

import pytest

from onyx.tools.tool_implementations.sandbox import patch as patch_module
from onyx.tools.tool_implementations.sandbox.patch import (
    MAX_UPDATE_LINES,
    AddFile,
    DeleteFile,
    PatchError,
    PatchHunk,
    UpdateChunk,
    UpdateFile,
    ensure_unique_targets,
    parse_patch,
    summarize,
    update_contents,
)

INVALID_HEADER_SUFFIX = (
    "is not a valid hunk header. Valid hunk headers: "
    "'*** Add File: {path}', '*** Delete File: {path}', '*** Update File: {path}'"
)
UNEXPECTED_LINE_SUFFIX = "Every line should start with ' ' (context line), '+' (added line), or '-' (removed line)"
FIRST_LINE_ERROR = (
    "invalid patch: The first line of the patch must be '*** Begin Patch'"
)
LAST_LINE_ERROR = "invalid patch: The last line of the patch must be '*** End Patch'"

SIMPLE_UPDATE = (
    "*** Begin Patch\n*** Update File: file2.py\n import foo\n+bar\n*** End Patch"
)
SIMPLE_UPDATE_HUNKS: list[PatchHunk] = [
    UpdateFile(
        path="file2.py",
        move_path=None,
        chunks=[
            UpdateChunk(
                old_lines=["import foo"],
                new_lines=["import foo", "bar"],
                context_line_indices=[(0, 0)],
            )
        ],
    )
]


def wrap_patch(body: str) -> str:
    return f"*** Begin Patch\n{body}\n*** End Patch"


def apply_update(original: str, patch: str) -> str:
    hunks = parse_patch(patch)
    assert len(hunks) == 1
    hunk = hunks[0]
    assert isinstance(hunk, UpdateFile)
    return update_contents(hunk.path, original, hunk.chunks)


@pytest.mark.parametrize(
    "patch, expected",
    [
        pytest.param(
            "*** Begin Patch \n*** Add File: foo\n+hi\n *** End Patch",
            [AddFile(path="foo", contents="hi\n")],
            id="whitespace_padded_envelope",
        ),
        pytest.param(
            wrap_patch(
                "*** Add File: path/add.py\n+abc\n+def\n"
                "*** Delete File: path/delete.py\n"
                "*** Update File: path/update.py\n*** Move to: path/update2.py\n"
                "@@ def f():\n-    pass\n+    return 123"
            ),
            [
                AddFile(path="path/add.py", contents="abc\ndef\n"),
                DeleteFile(path="path/delete.py"),
                UpdateFile(
                    path="path/update.py",
                    move_path="path/update2.py",
                    chunks=[
                        UpdateChunk(
                            change_context="def f():",
                            old_lines=["    pass"],
                            new_lines=["    return 123"],
                        )
                    ],
                ),
            ],
            id="add_delete_update_move",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: file.py\n@@\n+line\n*** Add File: other.py\n+content"
            ),
            [
                UpdateFile(
                    path="file.py",
                    move_path=None,
                    chunks=[UpdateChunk(new_lines=["line"])],
                ),
                AddFile(path="other.py", contents="content\n"),
            ],
            id="update_then_add",
        ),
        pytest.param(
            SIMPLE_UPDATE, SIMPLE_UPDATE_HUNKS, id="first_chunk_without_header"
        ),
        pytest.param(
            f"<<EOF\n{SIMPLE_UPDATE}\nEOF\n", SIMPLE_UPDATE_HUNKS, id="heredoc"
        ),
        pytest.param(
            f"<<'EOF'\n{SIMPLE_UPDATE}\nEOF\n",
            SIMPLE_UPDATE_HUNKS,
            id="single_quoted_heredoc",
        ),
        pytest.param(
            f'<<"EOF"\n{SIMPLE_UPDATE}\nEOF\n',
            SIMPLE_UPDATE_HUNKS,
            id="double_quoted_heredoc",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n+quux\n*** End of File\n"),
            [
                UpdateFile(
                    path="file.txt",
                    move_path=None,
                    chunks=[UpdateChunk(new_lines=["quux"], is_end_of_file=True)],
                )
            ],
            id="end_of_file_marker_then_blank_line",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: a.txt\n@@\n-old a\n+new a\n *** Update File: b.txt\n"
                "@@\n-old b\n+new b"
            ),
            [
                UpdateFile(
                    path="a.txt",
                    move_path=None,
                    chunks=[
                        UpdateChunk(
                            old_lines=["old a", "*** Update File: b.txt"],
                            new_lines=["new a", "*** Update File: b.txt"],
                            context_line_indices=[(1, 1)],
                        ),
                        UpdateChunk(old_lines=["old b"], new_lines=["new b"]),
                    ],
                )
            ],
            id="indented_marker_is_context",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: file.txt\n@@\n context before\n\n context after"
            ),
            [
                UpdateFile(
                    path="file.txt",
                    move_path=None,
                    chunks=[
                        UpdateChunk(
                            old_lines=["context before", "", "context after"],
                            new_lines=["context before", "", "context after"],
                            context_line_indices=[(0, 0), (1, 1), (2, 2)],
                        )
                    ],
                )
            ],
            id="bare_empty_line_is_context",
        ),
        pytest.param(
            "*** Begin Patch\r\n*** Update File: file.txt\r\n@@\r\n-old\r\r\n+new\r\n"
            "*** End Patch\r\n",
            [
                UpdateFile(
                    path="file.txt",
                    move_path=None,
                    chunks=[UpdateChunk(old_lines=["old\r"], new_lines=["new"])],
                )
            ],
            id="crlf_patch_text",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n-old\n+new") + "\n \t\n",
            [
                UpdateFile(
                    path="file.txt",
                    move_path=None,
                    chunks=[UpdateChunk(old_lines=["old"], new_lines=["new"])],
                )
            ],
            id="whitespace_after_end_patch",
        ),
        pytest.param(
            "*** Begin Patch\n*** Update File: file.txt\n@@\n-old\n+new\n *** End Patch",
            [
                UpdateFile(
                    path="file.txt",
                    move_path=None,
                    chunks=[UpdateChunk(old_lines=["old"], new_lines=["new"])],
                )
            ],
            id="indented_final_end_patch_ends_update",
        ),
        pytest.param(
            wrap_patch("*** Add File: a.txt\n+x\n*** End Patch\n"),
            [AddFile(path="a.txt", contents="x\n")],
            id="repeated_end_patch",
        ),
        pytest.param(
            wrap_patch("*** Update File: /abs/update.py\n@@\n-old\n+new"),
            [
                UpdateFile(
                    path="/abs/update.py",
                    move_path=None,
                    chunks=[UpdateChunk(old_lines=["old"], new_lines=["new"])],
                )
            ],
            id="absolute_path_kept_as_spelled",
        ),
    ],
)
def test_parse_patch(patch: str, expected: list[PatchHunk]) -> None:
    assert parse_patch(patch) == expected


@pytest.mark.parametrize(
    "patch, message",
    [
        pytest.param("bad", FIRST_LINE_ERROR, id="missing_begin"),
        pytest.param("", LAST_LINE_ERROR, id="empty_text"),
        pytest.param("*** Begin Patch\nbad", LAST_LINE_ERROR, id="missing_end"),
        pytest.param(
            f"<<\"EOF'\n{SIMPLE_UPDATE}\nEOF\n",
            FIRST_LINE_ERROR,
            id="mismatched_heredoc",
        ),
        pytest.param(
            "<<EOF\n*** Begin Patch\n*** Update File: file2.py\nEOF\n",
            LAST_LINE_ERROR,
            id="heredoc_missing_end_patch",
        ),
        pytest.param(
            wrap_patch("*** Add File: a.txt\n+x\n*** End Patch\nextra"),
            LAST_LINE_ERROR,
            id="content_after_end_patch",
        ),
        pytest.param(
            "*** Begin Patch\n*** End Patch", "No files were modified.", id="no_hunks"
        ),
        pytest.param(
            wrap_patch("bad"),
            f"invalid hunk at line 2, 'bad' {INVALID_HEADER_SUFFIX}",
            id="invalid_hunk_header",
        ),
        pytest.param(
            wrap_patch("*** Add File: file.txt\nbad"),
            f"invalid hunk at line 3, 'bad' {INVALID_HEADER_SUFFIX}",
            id="add_line_without_plus",
        ),
        pytest.param(
            wrap_patch("*** Delete File: file.txt\nbad"),
            f"invalid hunk at line 3, 'bad' {INVALID_HEADER_SUFFIX}",
            id="delete_with_body",
        ),
        pytest.param(
            wrap_patch("*** Environment ID: remote\n*** Add File: a.txt\n+x"),
            f"invalid hunk at line 2, '*** Environment ID: remote' {INVALID_HEADER_SUFFIX}",
            id="environment_id_unsupported",
        ),
        pytest.param(
            wrap_patch("*** Update File: test.py"),
            "invalid hunk at line 2, Update file hunk for path 'test.py' is empty",
            id="empty_update",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: old.txt\n*** Move to: new.txt\n*** Delete File: other.txt"
            ),
            "invalid hunk at line 2, Update file hunk for path 'old.txt' is empty",
            id="move_without_chunks",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@"),
            "invalid hunk at line 4, Update hunk does not contain any lines",
            id="header_without_lines",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n*** End of File"),
            "invalid hunk at line 4, Update hunk does not contain any lines",
            id="end_of_file_without_lines",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n@@"),
            f"invalid hunk at line 4, Unexpected line found in update hunk: '@@'. "
            f"{UNEXPECTED_LINE_SUFFIX}",
            id="consecutive_headers",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n-old\nbad"),
            "invalid hunk at line 5, Expected update hunk to start with a @@ context marker, "
            "got: 'bad'",
            id="unprefixed_line_after_changes",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: file.txt\n@@\n*** Update File: other.txt\n@@\n+x"
            ),
            "invalid hunk at line 4, Unexpected line found in update hunk: "
            f"'*** Update File: other.txt'. {UNEXPECTED_LINE_SUFFIX}",
            id="empty_chunk_before_next_hunk",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\nbad"),
            "invalid hunk at line 3, Unexpected line found in update hunk: 'bad'. "
            f"{UNEXPECTED_LINE_SUFFIX}",
            id="unprefixed_first_update_line",
        ),
        pytest.param(
            wrap_patch("*** Update File: file.txt\n@@\n-a\n+b\n*** End of File\n-c"),
            "invalid hunk at line 7, Expected update hunk to start with a @@ context marker, "
            "got: '-c'",
            id="lines_after_end_of_file_need_header",
        ),
    ],
)
def test_parse_patch_errors(patch: str, message: str) -> None:
    with pytest.raises(PatchError) as exc_info:
        parse_patch(patch)
    assert str(exc_info.value) == message


@pytest.mark.parametrize(
    "patch, message",
    [
        pytest.param(
            wrap_patch(
                "*** Update File: a.txt\n@@\n-x\n+y\n*** Update File: a.txt\n@@\n-y\n+z"
            ),
            "multiple operations target a.txt",
            id="duplicate_update",
        ),
        pytest.param(
            wrap_patch("*** Add File: a.txt\n+x\n*** Delete File: a.txt"),
            "multiple operations target a.txt",
            id="add_and_delete",
        ),
        pytest.param(
            wrap_patch(
                "*** Delete File: b.txt\n*** Update File: a.txt\n*** Move to: b.txt\n@@\n-x\n+y"
            ),
            "multiple operations target b.txt",
            id="move_destination_collides",
        ),
        pytest.param(
            wrap_patch(
                "*** Update File: a.txt\n*** Move to: b.txt\n@@\n-x\n+y\n*** Add File: b.txt\n+z"
            ),
            "multiple operations target b.txt",
            id="later_hunk_collides_with_move_destination",
        ),
        pytest.param(
            wrap_patch("*** Update File: a.txt\n*** Move to: a.txt\n@@\n-x\n+y"),
            "multiple operations target a.txt",
            id="move_onto_itself",
        ),
    ],
)
def test_ensure_unique_targets(patch: str, message: str) -> None:
    with pytest.raises(PatchError) as exc_info:
        ensure_unique_targets(parse_patch(patch), str)
    assert str(exc_info.value) == message


def test_ensure_unique_targets_counts_two_paths_of_one_file_once() -> None:
    files = {"alias/real.txt": "real.txt"}
    with pytest.raises(PatchError) as exc_info:
        ensure_unique_targets(
            parse_patch(
                wrap_patch(
                    "*** Update File: alias/real.txt\n@@\n-x\n+y\n"
                    "*** Delete File: real.txt"
                )
            ),
            lambda path: files.get(path, path),
        )
    assert str(exc_info.value) == "multiple operations target real.txt"


def test_parse_patch_keeps_hunk_order_across_many_kinds() -> None:
    patch = wrap_patch(
        "*** Add File: docs/release-notes.md\n+# Release notes\n+\n+## CLI\n"
        "*** Update File: src/config.rs\n@@ impl Config\n-    a: bool,\n+    b: bool,\n"
        "     c: bool,\n@@ fn interval()\n-    500\n+    250\n"
        "*** Delete File: src/legacy.rs\n"
        "*** Update File: crates/cli/src/main.rs\n*** Move to: crates/cli/src/bin/tool.rs\n"
        "@@ fn run()\n-    old()\n+    new()\n"
        "*** Add File: tests/fixture.json\n+{}\n"
        "*** Update File: README.md\n@@ Development workflow\n Build first.\n+Test too.\n"
        "*** Delete File: docs/old.md"
    )
    kinds = [
        (
            "add"
            if isinstance(hunk, AddFile)
            else "delete"
            if isinstance(hunk, DeleteFile)
            else "move-update"
            if hunk.move_path
            else "update"
        )
        for hunk in parse_patch(patch)
    ]
    assert kinds == [
        "add",
        "update",
        "delete",
        "move-update",
        "add",
        "update",
        "delete",
    ]


@pytest.mark.parametrize(
    "original, body, expected",
    [
        pytest.param(
            "foo\nbar\nbaz\nqux\n",
            "@@\n foo\n-bar\n+BAR\n@@\n baz\n-qux\n+QUX",
            "foo\nBAR\nbaz\nQUX\n",
            id="multiple_chunks",
        ),
        pytest.param(
            "foo\nbar\nbaz\n",
            "@@\n-foo\n+FOO\n bar\n",
            "FOO\nbar\nbaz\n",
            id="first_line",
        ),
        # The patch ends with an empty context line that matches only after the
        # trailing-empty-line retry.
        pytest.param(
            "foo\nbar\nbaz\n",
            "@@\n foo\n bar\n-baz\n+BAZ\n",
            "foo\nbar\nBAZ\n",
            id="last_line_trailing_empty_retry",
        ),
        pytest.param(
            "foo\nbar\nbaz\n",
            "@@\n+quux\n*** End of File",
            "foo\nbar\nbaz\nquux\n",
            id="insert_at_eof",
        ),
        pytest.param(
            "a\nb\nc\nd\ne\nf\n",
            "@@\n a\n-b\n+B\n@@\n c\n d\n-e\n+E\n@@\n f\n+g\n*** End of File",
            "a\nB\nc\nd\nE\nf\ng\n",
            id="interleaved_changes",
        ),
        pytest.param(
            "line1\nline2\nline3\n",
            "@@\n+after-context\n+second-line\n@@\n line1\n-line2\n-line3\n+line2-replacement",
            "line1\nline2-replacement\nafter-context\nsecond-line\n",
            id="pure_addition_without_context_appends",
        ),
        pytest.param(
            "import asyncio  # local import \u2013 avoids top\u2011level dep\n",
            "@@\n-import asyncio  # local import - avoids top-level dep\n+import asyncio  # HELLO",
            "import asyncio  # HELLO\n",
            id="unicode_dash_normalization",
        ),
        pytest.param(
            "line1\nna\u00efve caf\u00e9\nline3\n",
            "@@\n line1\n-na\u00efve caf\u00e9\n+na\u00efve caf\u00e9 \U0001f600",
            "line1\nna\u00efve caf\u00e9 \U0001f600\nline3\n",
            id="unicode_content",
        ),
        pytest.param(
            "no newline at end",
            "@@\n-no newline at end\n+first line\n+second line",
            "first line\nsecond line\n",
            id="appends_trailing_newline",
        ),
        pytest.param(
            "line1\nline2\n",
            "@@\n+added line 1\n+added line 2",
            "line1\nline2\nadded line 1\nadded line 2\n",
            id="pure_addition",
        ),
        pytest.param(
            "line1\nline2\nline3\n",
            "@@\n line1\n-line2\n line3",
            "line1\nline3\n",
            id="deletion_only",
        ),
        pytest.param(
            "first\nsecond\n",
            "@@\n first\n-second\n+second updated\n*** End of File",
            "first\nsecond updated\n",
            id="end_of_file_marker",
        ),
        pytest.param(
            "one\r\ntwo\r\nthree\r\n",
            "@@\n-one\n+ONE\n two\n+between\n three",
            "ONE\r\ntwo\r\nbetween\r\nthree\r\n",
            id="preserves_crlf",
        ),
        pytest.param(
            "one\r\ntwo\rthree\nfour\r\n",
            "@@\n one\n two\n-three\n+THREE\n four",
            "one\r\ntwo\rTHREE\r\nfour\r\n",
            id="preserves_mixed_line_endings",
        ),
        pytest.param(
            "  foo  \nbar\n",
            "@@\n foo\n-bar\n+BAR",
            "  foo  \nBAR\n",
            id="fuzzy_context_keeps_source_text",
        ),
        pytest.param(
            "class A:\n    def f(self):\n        pass\n\nclass B:\n    def f(self):\n        pass\n",
            "@@ class B:\n-    def f(self):\n+    def g(self):",
            "class A:\n    def f(self):\n        pass\n\nclass B:\n    def g(self):\n        pass\n",
            id="change_context_narrows_match",
        ),
        pytest.param(
            "def f():\n    return 1\n\ndef g():\n    return 2\n",
            "@@ def f():\n+    x = 1",
            "def f():\n    x = 1\n    return 1\n\ndef g():\n    return 2\n",
            id="pure_addition_inserts_after_context",
        ),
        pytest.param(
            "def f():\n    return 1\n",
            "@@ def f():\n+# end\n*** End of File",
            "def f():\n    return 1\n# end\n",
            id="pure_addition_with_context_and_eof_appends",
        ),
        pytest.param(
            "a\nb\nc\n",
            "@@ a\n+x\n@@\n-b\n+B",
            "a\nx\nB\nc\n",
            id="insertion_precedes_replacement_at_same_line",
        ),
        pytest.param("", "@@\n+hello", "hello\n", id="empty_file"),
        pytest.param(
            "foo   \nbar\t\t\n",
            "@@\n foo\n-bar\n+BAR",
            "foo   \nBAR\n",
            id="seek_ignores_trailing_whitespace",
        ),
        pytest.param(
            "    foo   \n   bar\t\n",
            "@@\n foo\n-bar\n+BAR",
            "    foo   \nBAR\n",
            id="seek_ignores_surrounding_whitespace",
        ),
        pytest.param(
            "x\na \u2013 b \u201cq\u201d\u00a0z\n",
            '@@\n-a - b "q" z\n+y',
            "x\ny\n",
            id="seek_folds_quotes_and_spaces",
        ),
        pytest.param(
            "a\nb\na\n",
            "@@\n-a\n+A\n@@\n-a\n+Z",
            "A\nb\nZ\n",
            id="seek_continues_after_the_previous_chunk",
        ),
        pytest.param(
            "a\nb\na\nb\n",
            "@@\n-a\n-b\n+X\n*** End of File",
            "a\nb\nX\n",
            id="end_of_file_matches_the_last_lines",
        ),
        pytest.param(
            "a\n",
            "@@\n-\n+tail\n*** End of File",
            "a\ntail\n",
            id="end_of_file_with_only_a_missing_blank_line_appends",
        ),
    ],
)
def test_update_contents(original: str, body: str, expected: str) -> None:
    assert (
        apply_update(original, wrap_patch(f"*** Update File: f.txt\n{body}"))
        == expected
    )


@pytest.mark.parametrize(
    "original, body, message",
    [
        pytest.param(
            "line1\nline2\n",
            "@@\n-missing\n+changed",
            "Failed to find expected lines in f.txt:\nmissing",
            id="missing_lines",
        ),
        pytest.param(
            "line1\n",
            "@@ nope\n-line1\n+x",
            "Failed to find context 'nope' in f.txt",
            id="missing_context",
        ),
        pytest.param(
            "a\nb\n",
            "@@\n-b\n+B\n@@\n-a\n+A",
            "Failed to find expected lines in f.txt:\na",
            id="chunks_must_be_in_order",
        ),
        pytest.param(
            "one\n",
            "@@\n-too\n-many\n-lines\n+x",
            "Failed to find expected lines in f.txt:\ntoo\nmany\nlines",
            id="more_lines_than_the_file",
        ),
        pytest.param(
            "a\nb\nc\n",
            "@@\n-a\n+x\n*** End of File",
            "Failed to find expected lines in f.txt:\na",
            id="end_of_file_requires_the_last_lines",
        ),
    ],
)
def test_update_contents_errors(original: str, body: str, message: str) -> None:
    with pytest.raises(PatchError) as exc_info:
        apply_update(original, wrap_patch(f"*** Update File: f.txt\n{body}"))
    assert str(exc_info.value) == message


def test_move_is_summarized_under_destination() -> None:
    hunks = parse_patch(
        wrap_patch("*** Update File: src.txt\n*** Move to: dst.txt\n@@\n-line\n+line2")
    )
    hunk = hunks[0]
    assert isinstance(hunk, UpdateFile)
    assert (hunk.path, hunk.move_path) == ("src.txt", "dst.txt")
    assert update_contents(hunk.path, "line\n", hunk.chunks) == "line2\n"
    assert summarize(hunks) == "Success. Updated the following files:\nM dst.txt\n"


def test_summarize_orders_added_modified_deleted() -> None:
    hunks = parse_patch(
        wrap_patch(
            "*** Delete File: gone.txt\n*** Update File: mod.txt\n@@\n-a\n+b\n"
            "*** Add File: new.txt\n+x\n*** Add File: new2.txt\n+y"
        )
    )
    assert summarize(hunks) == (
        "Success. Updated the following files:\nA new.txt\nA new2.txt\nM mod.txt\nD gone.txt\n"
    )


def test_a_search_over_repeated_lines_stays_linear() -> None:
    """Repeated lines and a long block whose last line is absent: a naive
    search compares the whole block at nearly every line."""
    body = "@@\n" + "-a\n" * 20_000 + "-b\n+c"
    started = time.monotonic()
    with pytest.raises(PatchError, match="Failed to find expected lines"):
        apply_update("a\n" * 200_000, wrap_patch(f"*** Update File: f.txt\n{body}"))
    assert time.monotonic() - started < 5


def test_the_searches_of_one_patch_stop_at_their_line_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each search is linear, but each hunk reads the rest of the file again:
    its exact pass misses the trailing space, then a lenient pass matches."""
    monkeypatch.setattr(patch_module, "MAX_SEEK_LINES", 10_000)
    original = "a \n" * 2_000
    one = wrap_patch("*** Update File: f.txt\n@@\n-a\n+b")
    assert apply_update(original, one).startswith("b\n")
    many = wrap_patch("*** Update File: f.txt\n" + "@@\n-a\n+b\n" * 10)
    with pytest.raises(PatchError, match="too large to verify"):
        apply_update(original, many)


def test_an_update_of_a_file_with_too_many_lines_fails_before_splitting() -> None:
    with pytest.raises(PatchError, match="more than 500000 lines"):
        apply_update(
            "\n" * (MAX_UPDATE_LINES + 1),
            wrap_patch("*** Update File: f.txt\n@@\n+tail\n*** End of File"),
        )
    # A CRLF ending ends one line.
    assert apply_update(
        "\r\n" * MAX_UPDATE_LINES,
        wrap_patch("*** Update File: f.txt\n@@\n+tail\n*** End of File"),
    ).endswith("\r\ntail\r\n")
