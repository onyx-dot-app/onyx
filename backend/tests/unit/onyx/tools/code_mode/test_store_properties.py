"""Property tests for store sizing and limits: programs choose every stored value."""

import json
from unittest.mock import patch

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from onyx.tools.tool_implementations.code_mode import store as store_module
from onyx.tools.tool_implementations.code_mode.models import (
    StoreSnapshot,
    entry_bytes,
    json_text,
)
from onyx.tools.tool_implementations.code_mode.store import (
    MAX_VALUE_DEPTH,
    ProgramStore,
    commit_limit_error,
    json_value,
)

# Text without lone surrogates: JSON escapes, control and multibyte characters.
_TEXT = st.text(st.characters(exclude_categories=("Cs",)), max_size=8)
_SCALAR = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    _TEXT,
)
# Tuples are sandbox sequences too; the copy turns them into lists.
_VALUE: st.SearchStrategy[object] = st.recursive(
    _SCALAR,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.lists(children, max_size=4).map(tuple),
        st.dictionaries(_TEXT, children, max_size=4),
    ),
    max_leaves=16,
)


def _with_surrogate(text: str, at: int, surrogate: str) -> str:
    at %= len(text) + 1
    return text[:at] + surrogate + text[at:]


@settings(max_examples=200, deadline=None, derandomize=True)
@given(value=_VALUE)
@example({"k": [1, "é", None, {"a": [], "b": {}}], "t": True, "f": -1.5e-7})
@example([])
@example("x")
@example([[[]], (1, 2)])
# Escapes and multibyte characters make the JSON longer than the text.
@example(['quote " and \\ backslash', "control \n\x00", "é, 中文 and 😀"])
@example({"é" * 10: [10**30, 1e16, False]})
def test_size_is_the_encoded_json_and_the_limit_is_exact(value: object) -> None:
    copied = json_value(value, "v", 10**9)

    assert copied.text == json_text(copied.value)
    assert copied.size == len(copied.text.encode("utf-8"))
    assert json.loads(copied.text) == copied.value
    # The copy accepts exactly its own size and rejects one byte less.
    assert json_value(value, "v", copied.size).size == copied.size
    with pytest.raises(
        ValueError, match=f"v exceeds the limit of {copied.size - 1} bytes"
    ):
        json_value(value, "v", copied.size - 1)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    doublings=st.integers(0, 200),
    max_bytes=st.integers(0, 4096),
    leaf=st.one_of(st.integers(), _TEXT),
)
# 2**64 leaves as JSON; the copy stops once it passes 1 KB.
@example(doublings=64, max_bytes=1024, leaf=1)
def test_shared_references_end_in_a_copy_or_a_size_error(
    doublings: int, max_bytes: int, leaf: object
) -> None:
    # x = [x, x]: the JSON doubles with each step, the object graph does not.
    value: object = [leaf]
    for _ in range(doublings):
        value = [value, value]

    try:
        copied = json_value(value, "v", max_bytes)
    except ValueError as error:
        message = str(error)
        assert len(message) < 2048
        # The value nests doublings + 1 lists.
        if doublings < MAX_VALUE_DEPTH:
            assert f"exceeds the limit of {max_bytes} bytes" in message
        else:
            assert "exceeds the limit" in message or "levels deep" in message
    else:
        assert copied.size <= max_bytes
        assert copied.size == len(copied.text.encode("utf-8"))


@settings(max_examples=150, deadline=None, derandomize=True)
@given(
    text=_TEXT,
    at=st.integers(0, 10),
    surrogate=st.characters(categories=("Cs",)),
    as_key=st.booleans(),
    depth=st.integers(0, 3),
    in_dict=st.booleans(),
)
@example(text="", at=0, surrogate="\ud800", as_key=False, depth=1, in_dict=True)
def test_lone_surrogates_are_a_value_error(
    text: str, at: int, surrogate: str, as_key: bool, depth: int, in_dict: bool
) -> None:
    bad = _with_surrogate(text, at, surrogate)
    value: object = {bad: 1} if as_key else bad
    for _ in range(depth):
        value = {"k": value} if in_dict else [value]

    with pytest.raises(ValueError):
        json_value(value, "v", 10_000)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(depth=st.integers(0, 3 * MAX_VALUE_DEPTH), use_dict=st.booleans())
@example(depth=MAX_VALUE_DEPTH, use_dict=False)
@example(depth=MAX_VALUE_DEPTH + 1, use_dict=False)
def test_nesting_depth_is_bounded(depth: int, use_dict: bool) -> None:
    value: object = 1
    for _ in range(depth):
        value = {"k": value} if use_dict else [value]

    if depth <= MAX_VALUE_DEPTH:
        assert json_value(value, "v", 10**6).value == value
    else:
        with pytest.raises(
            ValueError, match=f"nests more than {MAX_VALUE_DEPTH} levels deep"
        ):
            json_value(value, "v", 10**6)


_KEYS = st.sampled_from(["a", "b", "é", "long-key"])
_WRITE = st.one_of(st.none(), st.text(max_size=12), st.integers(), st.booleans())


@settings(max_examples=200, deadline=None, derandomize=True)
@given(
    initial=st.dictionaries(_KEYS, st.text(max_size=8), max_size=3),
    committed=st.integers(0, 40),
    writes=st.lists(st.tuples(_KEYS, _WRITE), max_size=8),
    store_limit=st.integers(0, 60),
    chat_limit=st.integers(0, 80),
)
# A store that fills the chat limit exactly, then a deletion.
@example(
    initial={"a": "x"},
    committed=40 - len('b"v"'),
    writes=[("b", "v"), ("a", None)],
    store_limit=60,
    chat_limit=40,
)
def test_store_limits_match_the_entry_sizes_and_the_commit_check(
    initial: dict[str, JsonValue],
    committed: int,
    writes: list[tuple[str, JsonValue]],
    store_limit: int,
    chat_limit: int,
) -> None:
    snapshot = StoreSnapshot(values=initial, committed_bytes=committed)

    def total(values: dict[str, JsonValue]) -> int:
        return sum(entry_bytes(key, value) for key, value in values.items())

    with (
        patch.object(store_module, "MAX_STORE_BYTES", store_limit),
        patch.object(store_module, "MAX_COMMITTED_BYTES", chat_limit),
    ):
        program = ProgramStore(snapshot)
        visible = dict(initial)
        for key, value in writes:
            before = total(visible)
            after_values = {k: v for k, v in visible.items() if k != key}
            if value is not None:
                after_values[key] = value
            after = total(after_values)
            try:
                program.store(key, value)
            except ValueError:
                # A deletion always passes.
                assert value is not None
                continue
            assert after <= store_limit or after <= before
            visible = after_values
            assert {k: program.load(k) for k in visible} == visible

        # The commit of a program whose store() calls all passed, with no other
        # program in between, passes the same limits.
        assert commit_limit_error(snapshot, program.changed_writes) is None
