from __future__ import annotations

import pytest

from onyx.utils.text_processing import parse_bracketed_list


@pytest.mark.parametrize(
    "content, expected",
    [
        ("[zendesk, asana]", ["zendesk", "asana"]),
        ('["zendesk", "asana"]', ["zendesk", "asana"]),
        ("[zendesk]", ["zendesk"]),
        ("[]", []),  # empty list found (distinct from None)
        ("Sure, here you go: [zendesk]", ["zendesk"]),  # stray text tolerated
        ("first [a] then [b, c]", ["b", "c"]),  # last bracketed list wins
        ("[ zendesk ,  asana ]", ["zendesk", "asana"]),  # whitespace trimmed
        ("no list here", None),  # no brackets -> None
        ("", None),
        (None, None),
    ],
)
def test_parse_bracketed_list(content: str | None, expected: list[str] | None) -> None:
    assert parse_bracketed_list(content) == expected
