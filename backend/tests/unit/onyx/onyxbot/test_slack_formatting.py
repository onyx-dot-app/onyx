from onyx.onyxbot.slack.formatting import _convert_slack_links_to_markdown
from onyx.onyxbot.slack.formatting import _normalize_link_destinations
from onyx.onyxbot.slack.formatting import _sanitize_html
from onyx.onyxbot.slack.formatting import _transform_outside_code_blocks
from onyx.onyxbot.slack.formatting import format_slack_message
from onyx.onyxbot.slack.utils import remove_slack_text_interactions
from onyx.utils.text_processing import decode_escapes


def test_normalize_citation_link_wraps_url_with_parentheses() -> None:
    message = (
        "See [[1]](https://example.com/Access%20ID%20Card(s)%20Guide.pdf) for details."
    )

    normalized = _normalize_link_destinations(message)

    assert (
        "See [[1]](<https://example.com/Access%20ID%20Card(s)%20Guide.pdf>) for details."
        == normalized
    )


def test_normalize_citation_link_keeps_existing_angle_brackets() -> None:
    message = "[[1]](<https://example.com/Access%20ID%20Card(s)%20Guide.pdf>)"

    normalized = _normalize_link_destinations(message)

    assert message == normalized


def test_normalize_citation_link_handles_multiple_links() -> None:
    message = (
        "[[1]](https://example.com/(USA)%20Guide.pdf) "
        "[[2]](https://example.com/Plan(s)%20Overview.pdf)"
    )

    normalized = _normalize_link_destinations(message)

    assert "[[1]](<https://example.com/(USA)%20Guide.pdf>)" in normalized
    assert "[[2]](<https://example.com/Plan(s)%20Overview.pdf>)" in normalized


def test_format_slack_message_keeps_parenthesized_citation_links_intact() -> None:
    message = (
        "Download [[1]](https://example.com/(USA)%20Access%20ID%20Card(s)%20Guide.pdf)"
    )

    formatted = format_slack_message(message)
    rendered = decode_escapes(remove_slack_text_interactions(formatted))

    assert (
        "<https://example.com/(USA)%20Access%20ID%20Card(s)%20Guide.pdf|[1]>"
        in rendered
    )
    assert "|[1]>%20Access%20ID%20Card" not in rendered


def test_slack_style_links_converted_to_clickable_links() -> None:
    message = "Visit <https://example.com/page|Example Page> for details."

    formatted = format_slack_message(message)

    assert "<https://example.com/page|Example Page>" in formatted
    assert "&lt;" not in formatted


def test_slack_style_links_preserved_inside_code_blocks() -> None:
    message = "```\n<https://example.com|click>\n```"

    converted = _convert_slack_links_to_markdown(message)

    assert "<https://example.com|click>" in converted


def test_html_tags_stripped_outside_code_blocks() -> None:
    message = "Hello<br/>world ```<div>code</div>``` after"

    sanitized = _transform_outside_code_blocks(message, _sanitize_html)

    assert "<br" not in sanitized
    assert "<div>code</div>" in sanitized


def test_format_slack_message_block_spacing() -> None:
    message = "Paragraph one.\n\nParagraph two."

    formatted = format_slack_message(message)

    assert "Paragraph one.\n\nParagraph two." == formatted


def test_format_slack_message_code_block_no_trailing_blank_line() -> None:
    message = "```python\nprint('hi')\n```"

    formatted = format_slack_message(message)

    assert formatted.endswith("print('hi')\n```")


def test_format_slack_message_ampersand_not_double_escaped() -> None:
    message = 'She said "hello" & goodbye.'

    formatted = format_slack_message(message)

    assert "&amp;" in formatted
    assert "&quot;" not in formatted
