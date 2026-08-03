from onyx.connectors.slack.utils import (
    _DEFANG_EXEMPT_REGION_PATTERN,
    _SUBTEAM_MENTION_PATTERN,
)
from onyx.onyxbot.slack.blocks import _clean_markdown_link_text
from onyx.onyxbot.slack.formatting import (
    _RENDERED_SLACK_LINK_PATTERN,
    _SLACK_LINK_PATTERN,
    _convert_slack_links_to_markdown,
    _normalize_link_destinations,
    _sanitize_html,
    _transform_outside_code_blocks,
    format_slack_message,
)
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
    message = "[[1]](https://example.com/(USA)%20Guide.pdf) [[2]](https://example.com/Plan(s)%20Overview.pdf)"

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


def test_slack_token_patterns_stop_at_nested_openers() -> None:
    nested_link = "<https://outer|label<https://nested>"
    nested_subteam = "<!subteam^S1<!subteam^S2>"

    assert _SLACK_LINK_PATTERN.fullmatch(nested_link) is None
    assert _RENDERED_SLACK_LINK_PATTERN.fullmatch(nested_link) is None
    assert _DEFANG_EXEMPT_REGION_PATTERN.fullmatch(nested_link) is None
    assert _SUBTEAM_MENTION_PATTERN.fullmatch(nested_subteam) is None


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


# -- Table rendering tests --


def test_table_renders_as_vertical_cards() -> None:
    message = "| Feature | Status | Owner |\n|---------|--------|-------|\n| Auth | Done | Alice |\n| Search | In Progress | Bob |\n"

    formatted = format_slack_message(message)

    assert "*Auth*\n  • Status: Done\n  • Owner: Alice" in formatted
    assert "*Search*\n  • Status: In Progress\n  • Owner: Bob" in formatted
    # Cards separated by blank line
    assert "Owner: Alice\n\n*Search*" in formatted
    # No raw pipe-and-dash table syntax
    assert "---|" not in formatted


def test_table_single_column() -> None:
    message = "| Name |\n|------|\n| Alice |\n| Bob |\n"

    formatted = format_slack_message(message)

    assert "*Alice*" in formatted
    assert "*Bob*" in formatted


def test_table_embedded_in_text() -> None:
    message = "Here are the results:\n\n| Item | Count |\n|------|-------|\n| Apples | 5 |\n\nThat's all."

    formatted = format_slack_message(message)

    assert "Here are the results:" in formatted
    assert "*Apples*\n  • Count: 5" in formatted
    assert "That's all." in formatted


def test_table_with_formatted_cells() -> None:
    message = "| Name | Link |\n|------|------|\n| **Alice** | [profile](https://example.com) |\n"

    formatted = format_slack_message(message)

    # Bold cell should not double-wrap: *Alice* not **Alice**
    assert "*Alice*" in formatted
    assert "**Alice**" not in formatted
    assert "<https://example.com|profile>" in formatted


def test_table_with_alignment_specifiers() -> None:
    message = "| Left | Center | Right |\n|:-----|:------:|------:|\n| a | b | c |\n"

    formatted = format_slack_message(message)

    assert "*a*\n  • Center: b\n  • Right: c" in formatted


def test_two_tables_in_same_message_use_independent_headers() -> None:
    message = "| A | B |\n|---|---|\n| 1 | 2 |\n\n| X | Y | Z |\n|---|---|---|\n| p | q | r |\n"

    formatted = format_slack_message(message)

    assert "*1*\n  • B: 2" in formatted
    assert "*p*\n  • Y: q\n  • Z: r" in formatted


def test_table_empty_first_column_no_bare_asterisks() -> None:
    message = "| Name | Status |\n|------|--------|\n| | Done |\n"

    formatted = format_slack_message(message)

    # Empty title should not produce "**" (bare asterisks)
    assert "**" not in formatted
    assert "  • Status: Done" in formatted


def _render(message: str) -> str:
    """Mirror the answer-block render path in blocks.py."""
    return decode_escapes(remove_slack_text_interactions(format_slack_message(message)))


def test_bold_url_delimiters_stay_outside_the_link() -> None:
    rendered = _render("See **https://onyx.app/docs** for details.")

    assert "See *<https://onyx.app/docs>* for details." == rendered


def test_unlinked_email_is_still_not_split_by_zero_width_space() -> None:
    # Rejected as a truncated local part, so it stays plain text and the
    # mention defanging is the only thing left that could corrupt it
    assert "a *support@onyx.app" == _render("a *support@onyx.app")


def test_italic_and_strikethrough_urls_stay_intact() -> None:
    assert "_<https://onyx.app>_" == _render("_https://onyx.app_")
    assert "~<https://onyx.app>~" == _render("~~https://onyx.app~~")


def test_bold_email_renders_as_mailto_link() -> None:
    rendered = _render("Contact **support@onyx.app** for help.")

    assert "Contact *<mailto:support@onyx.app|support@onyx.app>* for help." == rendered
    assert "_<mailto:support@onyx.app|support@onyx.app>_" == _render(
        "_support@onyx.app_"
    )
    assert "~<mailto:support@onyx.app|support@onyx.app>~" == _render(
        "~~support@onyx.app~~"
    )


def test_bare_email_is_not_split_by_zero_width_space() -> None:
    rendered = _render("plain support@onyx.app plain")

    assert "\u200b" not in rendered
    assert "<mailto:support@onyx.app|support@onyx.app>" in rendered


def test_mentions_are_still_defanged() -> None:
    rendered = _render("Ping <@U123> and @channel please")

    assert "@\u200bU123" in rendered
    assert "@\u200bchannel" in rendered


def test_all_slack_notification_shapes_are_defanged() -> None:
    message = (
        "<@U123> <@W123> <@B123> <!here> <!channel> <!everyone> "
        "<!subteam^S123> <!subteam^S456|@ops> @group"
    )

    cleaned = remove_slack_text_interactions(message)

    for mention in (
        "U123",
        "W123",
        "B123",
        "here",
        "channel",
        "everyone",
        "S123",
        "ops",
        "group",
    ):
        assert f"@\u200b{mention}" in cleaned
    assert "<!" not in cleaned


def test_email_specials_and_url_userinfo_survive_mention_defanging() -> None:
    email = "support!@onyx.app"
    url = "https://support!@onyx.app/docs"

    rendered = _render(f"{email} {url} `{email}`")

    assert f"<mailto:{email}|{email}>" in rendered
    assert f"<{url}>" in rendered
    assert f"`{email}`" in rendered
    assert "\u200b" not in rendered


def test_slack_style_mailto_link_survives_formatting() -> None:
    message = "<mailto:support@onyx.app|support@onyx.app>"

    assert message == _render(message)


def test_urls_and_emails_in_code_are_left_alone() -> None:
    assert "```\nhttps://onyx.app and a@b.com\n```" == _render(
        "```\nhttps://onyx.app and a@b.com\n```"
    )
    assert "code `a@b.com` span" == _render("code `a@b.com` span")


def test_ordered_list_resumes_numbering_after_a_fenced_block() -> None:
    # The fence closes the list, so the tail arrives as a separate list that
    # has to pick up where the first one stopped
    message = "1. one\n2. two:\n\n```\ncode\n```\n\n3. three"

    assert message == format_slack_message(message)


def test_blockquoted_list_is_not_treated_as_nested() -> None:
    # mistune counts every block container in attrs["depth"], so only list
    # ancestry may indent
    assert ">1. alpha\n>2. beta" == format_slack_message("> 1. alpha\n> 2. beta")
    assert ">• a\n>• b" == format_slack_message("> - a\n> - b")


def test_nested_list_opens_an_indented_line_of_its_own() -> None:
    assert "1. one\n2. two:\n  • a\n  • b\n3. three" == format_slack_message(
        "1. one\n2. two:\n   - a\n   - b\n3. three"
    )


def test_code_is_left_literal_by_every_pre_parse_transform() -> None:
    # Link conversion, HTML stripping and destination normalization all run
    # before mistune sees the text, so each has to honor the code guard
    for snippet in (
        "`<mailto:admin@onyx.app|admin@onyx.app>`",
        "`<https://onyx.app/docs|onyx.app/docs>`",
        "`<div>hi</div>`",
        "`[label](https://onyx.app/x)`",
    ):
        assert f"see {snippet} here" == format_slack_message(f"see {snippet} here")

    fenced = "```\n[label](https://onyx.app/x)\n```"
    assert fenced == format_slack_message(fenced)


def test_url_link_drops_redundant_label() -> None:
    assert "<https://onyx.app>" == _render("[https://onyx.app](https://onyx.app)")


def test_link_label_text_is_not_autolinked() -> None:
    # A nested <...> would terminate the citation link that wraps this title
    title = _clean_markdown_link_text("Runbook for https://onyx.app/docs")

    assert "Runbook for https://onyx.app/docs" == title
    assert "Contact support@onyx.app" == _clean_markdown_link_text(
        "Contact support@onyx.app"
    )
    assert "Read the portal" == _clean_markdown_link_text(
        "Read the [portal](https://onyx.app)"
    )
    assert "Visit https://onyx.app" == _clean_markdown_link_text(
        "Visit <https://onyx.app>"
    )


def test_markdown_link_keeps_nested_url_label_flat() -> None:
    rendered = _render("[outer https://nested.example](https://outer.example/a|b>c)")

    assert "<https://outer.example/a%7Cb%3Ec|outer https://nested.example>" == rendered


def test_image_labels_cannot_nest_slack_links() -> None:
    assert "<https://images.example/a.png|https://alt.example>" == _render(
        "![https://alt.example](https://images.example/a.png)"
    )
    assert "<https://images.example/a.png|https://alt.example>" == _render(
        "![<https://alt.example>](https://images.example/a.png)"
    )


def test_trailing_punctuation_excluded_from_url() -> None:
    assert "trailing <https://onyx.app/docs>. Done" == _render(
        "trailing https://onyx.app/docs. Done"
    )


def test_balanced_url_parentheses_stay_inside_the_link() -> None:
    assert "<https://onyx.app/docs_(v2)>" == _render("https://onyx.app/docs_(v2)")
    assert "<https://onyx.app/docs>)))" == _render("https://onyx.app/docs)))")


def test_url_delimiters_and_short_hosts_do_not_break_slack_links() -> None:
    assert "<https://x>" == _render("https://x")
    assert "<https://onyx.app>|label" == _render("https://onyx.app|label")


def test_email_autolinking_does_not_match_an_overlong_local_part() -> None:
    repeated_specials = [character * 65 for character in ("a", "!", ".", "*", "_", "~")]
    mixed_specials = [character + "a" * 64 for character in ("!", "*", "_", "~")]
    for local_part in repeated_specials + mixed_specials:
        message = f"{local_part}@example.com"
        assert "mailto:" not in format_slack_message(message)
