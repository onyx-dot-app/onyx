from onyx.llm.tool_parsing import XmlToolCallContentFilter


class TestXmlToolCallContentFilter:
    def test_strips_function_calls_block_single_chunk(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process(
            "prefix "
            '<function_calls><invoke name="internal_search">'
            '<parameter name="queries" string="false">["Onyx docs"]</parameter>'
            "</invoke></function_calls> suffix"
        )
        output += f.flush()
        assert output == "prefix suffix"

    def test_strips_function_calls_block_split_across_chunks(self) -> None:
        f = XmlToolCallContentFilter()
        chunks = [
            "Start ",
            "<function_",
            'calls><invoke name="internal_search">',
            '<parameter name="queries" string="false">["Onyx docs"]',
            "</parameter></invoke></function_calls>",
            " End",
        ]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "Start End"

    def test_whitespace_after_block_split_across_chunks_is_dropped(self) -> None:
        f = XmlToolCallContentFilter()
        chunks = [
            "before ",
            "<function_calls><invoke></invoke></function_calls>",
            "  ",
            "\t",
            "after",
        ]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "before after"

    def test_newline_after_block_is_kept_after_space(self) -> None:
        f = XmlToolCallContentFilter()
        chunks = [
            "Text ",
            "<function_calls><invoke></invoke></function_calls>",
            "  ",
            "\n",
            "## Details",
        ]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "Text \n## Details"

    def test_indentation_after_block_is_kept(self) -> None:
        f = XmlToolCallContentFilter()
        chunks = [
            "Intro\n",
            "<function_calls><invoke></invoke></function_calls>",
            "\n  ",
            "  code",
        ]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "Intro\n\n    code"

    def test_indentation_on_block_line_is_kept(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process(
            "- item\n<function_calls><invoke></invoke></function_calls>  - nested"
        )
        output += f.flush()
        assert output == "- item\n  - nested"

    def test_block_at_start_drops_spaces_and_keeps_line_breaks(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process("<function_calls><invoke></invoke></function_calls>  ")
        output += f.process("\nAnswer")
        output += f.flush()
        assert output == "\nAnswer"

    def test_block_at_end_keeps_preceding_text(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process("Answer. <function_calls><invoke></invoke>")
        output += f.process("</function_calls> ")
        output += f.flush()
        assert output == "Answer. "

    def test_newline_separated_block_keeps_line_breaks(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process(
            "Line one.\n<function_calls><invoke></invoke></function_calls>\nLine two."
        )
        output += f.flush()
        assert output == "Line one.\n\nLine two."

    def test_whitespace_kept_when_none_precedes_block(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process(
            "before<function_calls><invoke></invoke></function_calls> after"
        )
        output += f.flush()
        assert output == "before after"

    def test_no_whitespace_around_block_does_not_add_any(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process("a<function_calls><invoke></invoke></function_calls>b")
        output += f.flush()
        assert output == "ab"

    def test_text_without_block_is_unchanged(self) -> None:
        f = XmlToolCallContentFilter()
        chunks = ["  Hello  ", "\n\n", "  world  "]
        output = "".join(f.process(chunk) for chunk in chunks) + f.flush()
        assert output == "  Hello  \n\n  world  "

    def test_preserves_non_tool_call_xml(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process("A <tag>value</tag> B")
        output += f.flush()
        assert output == "A <tag>value</tag> B"

    def test_does_not_strip_similar_tag_names(self) -> None:
        f = XmlToolCallContentFilter()
        output = f.process(
            "A <function_calls_v2><invoke>noop</invoke></function_calls_v2> B"
        )
        output += f.flush()
        assert (
            output == "A <function_calls_v2><invoke>noop</invoke></function_calls_v2> B"
        )
