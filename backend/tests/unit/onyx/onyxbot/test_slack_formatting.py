from onyx.onyxbot.slack.formatting import _normalize_citation_link_destinations
from onyx.onyxbot.slack.formatting import format_slack_message
from onyx.onyxbot.slack.utils import remove_slack_text_interactions
from onyx.utils.text_processing import decode_escapes


def test_normalize_citation_link_wraps_url_with_parentheses() -> None:
    message = (
        "See [[1]](https://example.com/Access%20ID%20Card(s)%20Guide.pdf) for details."
    )

    normalized = _normalize_citation_link_destinations(message)

    assert (
        "See [[1]](<https://example.com/Access%20ID%20Card(s)%20Guide.pdf>) for details."
        == normalized
    )


def test_normalize_citation_link_keeps_existing_angle_brackets() -> None:
    message = "[[1]](<https://example.com/Access%20ID%20Card(s)%20Guide.pdf>)"

    normalized = _normalize_citation_link_destinations(message)

    assert message == normalized


def test_normalize_citation_link_handles_multiple_links() -> None:
    message = (
        "[[1]](https://example.com/(USA)%20Guide.pdf) "
        "[[2]](https://example.com/Plan(s)%20Overview.pdf)"
    )

    normalized = _normalize_citation_link_destinations(message)

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
