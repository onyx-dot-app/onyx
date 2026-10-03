import pytest

from onyx.utils.text_processing import clean_text


@pytest.mark.parametrize(
    "text",
    [
        "Collect signatures for 1\u20132 weeks at 1\u20135%; use 3\u20136 clusters.",
        "The customer\u2019s \u2018approved\u2019 range is \u201c10\u201320\u201d.",
        "First\u2002second\u2028third\u2029fourth",
    ],
)
def test_clean_text_preserves_punctuation_and_word_boundaries(text: str) -> None:
    assert clean_text(text) == text


def test_clean_text_still_removes_controls() -> None:
    assert clean_text("a\x00\x01\u200b\u202e\u2060\u2066\u206ab\n\tc") == "ab\n\tc"
