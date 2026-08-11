"""Tests for rendering Atlassian Document Format content as plain text."""

from typing import Any

from onyx.connectors.jira.adf import extract_text_from_adf


def _doc(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": list(content)}


def _paragraph(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def _text(text: str, marks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return node


def _cell(node_type: str, text: str) -> dict[str, Any]:
    return {"type": node_type, "content": [_paragraph(_text(text))]}


def test_none_and_empty_docs() -> None:
    assert extract_text_from_adf(None) == ""
    assert extract_text_from_adf(_doc()) == ""
    # Empty paragraphs are layout spacers and carry no content.
    assert extract_text_from_adf(_doc(_paragraph())) == ""


def test_single_paragraph_is_returned_verbatim() -> None:
    doc = _doc(_paragraph(_text("We need magic!")))
    assert extract_text_from_adf(doc) == "We need magic!"


def test_inline_nodes_are_concatenated_without_added_spaces() -> None:
    """ADF splits marked-up text into several nodes that already carry spacing."""
    doc = _doc(
        _paragraph(
            _text("Set "),
            _text("CRMMODE_ENABLED", [{"type": "code"}]),
            _text(" to true."),
        )
    )
    assert extract_text_from_adf(doc) == "Set CRMMODE_ENABLED to true."


def test_paragraphs_are_separated_by_newlines() -> None:
    doc = _doc(_paragraph(_text("First.")), _paragraph(_text("Second.")))
    assert extract_text_from_adf(doc) == "First.\nSecond."


def test_headings_keep_their_level() -> None:
    doc = _doc(
        {"type": "heading", "attrs": {"level": 1}, "content": [_text("CRM/MTR")]},
        {"type": "heading", "attrs": {"level": 3}, "content": [_text("QFX")]},
    )
    assert extract_text_from_adf(doc) == "# CRM/MTR\n### QFX"


def test_link_mark_keeps_the_target() -> None:
    doc = _doc(
        _paragraph(
            _text(
                "release report",
                [{"type": "link", "attrs": {"href": "https://example.com/r/1"}}],
            )
        )
    )
    assert extract_text_from_adf(doc) == "release report (https://example.com/r/1)"


def test_link_mark_is_not_duplicated_when_text_is_the_url() -> None:
    url = "http://aws-elk1:8200"
    doc = _doc(_paragraph(_text(url, [{"type": "link", "attrs": {"href": url}}])))
    assert extract_text_from_adf(doc) == url


def test_bullet_list_with_nested_list_is_indented() -> None:
    nested = {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_paragraph(_text("OTEL_LOGS_EXPORTER"))]},
        ],
    }
    doc = _doc(
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [_paragraph(_text("Configure variables:")), nested],
                },
                {"type": "listItem", "content": [_paragraph(_text("Restart"))]},
            ],
        }
    )
    assert extract_text_from_adf(doc) == (
        "- Configure variables:\n  - OTEL_LOGS_EXPORTER\n- Restart"
    )


def test_ordered_list_numbers_items_from_the_start_attribute() -> None:
    doc = _doc(
        {
            "type": "orderedList",
            "attrs": {"order": 3},
            "content": [
                {"type": "listItem", "content": [_paragraph(_text("third"))]},
                {"type": "listItem", "content": [_paragraph(_text("fourth"))]},
            ],
        }
    )
    assert extract_text_from_adf(doc) == "3. third\n4. fourth"


def test_table_keeps_each_value_under_its_column() -> None:
    """The deployment tables in release tickets are only useful row-wise."""
    doc = _doc(
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        _cell("tableHeader", "Service"),
                        _cell("tableHeader", "Branch"),
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        _cell("tableCell", "auth-mtr"),
                        _cell("tableCell", "release_1_6_2"),
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        _cell("tableCell", "bo-payment"),
                        _cell("tableCell", "release_3_20_5"),
                    ],
                },
            ],
        }
    )
    assert extract_text_from_adf(doc) == (
        "| Service | Branch |\n"
        "| --- | --- |\n"
        "| auth-mtr | release_1_6_2 |\n"
        "| bo-payment | release_3_20_5 |"
    )


def test_table_without_header_row_has_no_separator() -> None:
    doc = _doc(
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableCell", "a"), _cell("tableCell", "b")],
                }
            ],
        }
    )
    assert extract_text_from_adf(doc) == "| a | b |"


def test_table_cell_block_content_is_flattened_to_one_line() -> None:
    cell_with_blocks = {
        "type": "tableCell",
        "content": [
            _paragraph(_text("Notes")),
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [_paragraph(_text("first"))]},
                    {"type": "listItem", "content": [_paragraph(_text("second"))]},
                ],
            },
        ],
    }
    doc = _doc(
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableCell", "svc"), cell_with_blocks],
                }
            ],
        }
    )
    assert extract_text_from_adf(doc) == "| svc | Notes - first - second |"


def test_table_cell_pipe_is_escaped() -> None:
    doc = _doc(
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [_cell("tableCell", "a|b"), _cell("tableCell", "c")],
                }
            ],
        }
    )
    assert extract_text_from_adf(doc) == r"| a\|b | c |"


def test_code_block_is_fenced_with_its_language() -> None:
    doc = _doc(
        {
            "type": "codeBlock",
            "attrs": {"language": "sql"},
            "content": [_text("DROP TABLE lead_assignment;")],
        }
    )
    assert extract_text_from_adf(doc) == "```sql\nDROP TABLE lead_assignment;\n```"


def test_blockquote_and_panel() -> None:
    quote = {"type": "blockquote", "content": [_paragraph(_text("quoted"))]}
    assert extract_text_from_adf(_doc(quote)) == "> quoted"

    panel = {
        "type": "panel",
        "attrs": {"panelType": "warning"},
        "content": [_paragraph(_text("UWAGA")), _paragraph(_text("second line"))],
    }
    assert extract_text_from_adf(_doc(panel)) == "[warning] UWAGA\nsecond line"


def test_task_list_marks_completion() -> None:
    doc = _doc(
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"state": "DONE"},
                    "content": [_text("deployed")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"state": "TODO"},
                    "content": [_text("verify")],
                },
            ],
        }
    )
    assert extract_text_from_adf(doc) == "- [x] deployed\n- [ ] verify"


def test_inline_card_url_is_kept() -> None:
    """Smart links in release tables hold the version URL and nothing else."""
    url = "https://example.atlassian.net/projects/CRM/versions/33941"
    doc = _doc(_paragraph({"type": "inlineCard", "attrs": {"url": url}}))
    assert extract_text_from_adf(doc) == url


def test_block_card_url_from_json_ld_data() -> None:
    doc = _doc(
        _paragraph(
            {"type": "blockCard", "attrs": {"data": {"url": "https://example.com/x"}}}
        )
    )
    assert extract_text_from_adf(doc) == "https://example.com/x"


def test_mention_emoji_status_and_hard_break() -> None:
    doc = _doc(
        _paragraph(
            {"type": "mention", "attrs": {"text": "@Adam Serafin"}},
            _text(" says "),
            {"type": "status", "attrs": {"text": "DONE"}},
            {"type": "hardBreak"},
            {"type": "emoji", "attrs": {"text": "✅", "shortName": ":check:"}},
        )
    )
    assert extract_text_from_adf(doc) == "@Adam Serafin says DONE\n✅"


def test_date_node_is_rendered_as_a_date() -> None:
    # 1750377600000 ms == 2025-06-20 UTC
    doc = _doc(_paragraph({"type": "date", "attrs": {"timestamp": "1750377600000"}}))
    assert extract_text_from_adf(doc) == "2025-06-20"


def test_media_uses_alt_text_when_present() -> None:
    with_alt = {
        "type": "mediaSingle",
        "content": [{"type": "media", "attrs": {"alt": "topology.png", "id": "x"}}],
    }
    assert extract_text_from_adf(_doc(with_alt)) == "[media: topology.png]"

    without_alt = {
        "type": "mediaSingle",
        "content": [{"type": "media", "attrs": {"id": "x"}}],
    }
    assert extract_text_from_adf(_doc(without_alt)) == ""


def test_expand_keeps_its_title_and_body() -> None:
    doc = _doc(
        {
            "type": "expand",
            "attrs": {"title": "Rollback steps"},
            "content": [_paragraph(_text("stop the service"))],
        }
    )
    assert extract_text_from_adf(doc) == "Rollback steps\nstop the service"


def test_unknown_node_types_degrade_to_their_content() -> None:
    """Unknown/new ADF nodes must never drop the text they wrap."""
    doc = _doc(
        {
            "type": "someFutureLayout",
            "content": [_paragraph(_text("still indexed"))],
        }
    )
    assert extract_text_from_adf(doc) == "still indexed"


def test_unknown_leaf_node_keeps_its_text() -> None:
    doc = _doc({"type": "someFutureLeaf", "text": "kept"})
    assert extract_text_from_adf(doc) == "kept"


def test_rule_is_dropped() -> None:
    doc = _doc(_paragraph(_text("a")), {"type": "rule"}, _paragraph(_text("b")))
    assert extract_text_from_adf(doc) == "a\nb"
