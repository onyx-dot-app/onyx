"""Property tests for partial JSON parsing: tool call arguments stream in
fragments of any size, and the model chooses every character."""

import json

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from onyx.utils.streaming_json import appended_text, parse_partial_object

# Any text a model can send: escapes, control characters, astral characters.
# Lone surrogates are not valid JSON text, so they are left out.
_TEXT = st.text(st.characters(exclude_categories=("Cs",)), max_size=10)
_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**20), max_value=10**20),
    st.floats(allow_nan=False, allow_infinity=False),
    _TEXT,
)
_VALUE: st.SearchStrategy[JsonValue] = st.recursive(
    _SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(_TEXT, children, max_size=3),
    ),
    max_leaves=10,
)
_OBJECT = st.dictionaries(_TEXT, _VALUE, max_size=4)


@st.composite
def _document(draw: st.DrawFn, values: st.SearchStrategy[JsonValue]) -> str:
    return json.dumps(
        draw(values),
        ensure_ascii=draw(st.booleans()),
        indent=draw(st.sampled_from([None, 0, 2])),
    )


def _split(text: str, cuts: list[int]) -> list[str]:
    points = sorted({cut % (len(text) + 1) for cut in cuts})
    return [
        text[start:end]
        for start, end in zip([0, *points], [*points, len(text)], strict=True)
    ]


@settings(max_examples=150, deadline=None, derandomize=True)
@given(document=_document(_OBJECT))
def test_every_prefix_parses_and_the_whole_matches_json_loads(document: str) -> None:
    expected = json.loads(document)

    for end in range(len(document) + 1):
        partial = parse_partial_object(document[:end])
        # Text strings stay valid: no half of a surrogate pair.
        json.dumps(partial, ensure_ascii=False).encode("utf-8")
        for key, value in partial.items():
            # A string field only grows toward its final value.
            if isinstance(value, str):
                assert expected[key].startswith(value)

    assert parse_partial_object(document) == expected


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    document=_document(_OBJECT),
    cuts=st.lists(st.integers(0, 10_000), max_size=8),
)
def test_appended_text_rebuilds_each_string_field(
    document: str, cuts: list[int]
) -> None:
    expected = json.loads(document)
    text = ""
    previous: dict[str, JsonValue] = {}
    joined: dict[str, str] = {}
    for chunk in _split(document, cuts):
        text += chunk
        current = parse_partial_object(text)
        for key, added in appended_text(previous, current).items():
            joined[key] = joined.get(key, "") + added
        previous = current

    assert previous == expected
    assert joined == {
        key: value
        for key, value in expected.items()
        if isinstance(value, str) and value
    }


@settings(max_examples=100, deadline=None, derandomize=True)
@given(document=_document(_VALUE.filter(lambda value: not isinstance(value, dict))))
def test_documents_that_are_not_objects_parse_as_empty(document: str) -> None:
    for end in range(len(document) + 1):
        assert parse_partial_object(document[:end]) == {}
