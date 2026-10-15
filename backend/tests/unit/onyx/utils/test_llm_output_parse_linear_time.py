"""LLM output parsers must stay linear on adversarial model output."""

import gc
import signal
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

import pytest

from onyx.llm.models import ToolDefinition
from onyx.llm.tool_parsing import extract_tool_calls_from_response_text
from onyx.secondary_llm_flows.time_filter import (
    _TIME_FILTER_PAIR_RE,
    _parse_time_decision,
)
from onyx.utils.text_processing import find_all_json_objects, parse_llm_json_response

# Each adversarial case runs at n and _GROWTH x n. Linear code grows about
# _GROWTH times; the old quadratic and cubic scans grew 64x to 512x. Comparing
# growth instead of wall time keeps the tests stable on slow, shared runners.
_GROWTH = 8
_MAX_GROWTH_RATIO = 32.0
# Below this, the large run is too fast for any quadratic regression to matter.
_NOISE_FLOOR_SECONDS = 0.01
# Stall guard per call. SIGALRM interrupts a stalled parser (sre and the
# Python loop both check signals), so a regression fails instead of hanging.
_STALL_SECONDS = 10.0
_ROUNDS = 3

_TOOLS = [
    ToolDefinition(
        name="internal_search",
        description="",
        parameters={"type": "object", "properties": {"queries": {}}},
    )
]


def _timed(fn: Callable[[], Any]) -> float:
    def _on_timeout(_signum: int, _frame: FrameType | None) -> None:
        raise TimeoutError(f"took more than {_STALL_SECONDS}s")

    # GC passes over the parsed objects grow with the heap, not with the
    # parser's own work, so they are kept out of the measurement.
    gc.collect()
    gc.disable()
    previous_handler = signal.signal(signal.SIGALRM, _on_timeout)
    signal.setitimer(signal.ITIMER_REAL, _STALL_SECONDS)
    started = time.perf_counter()
    try:
        fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        gc.enable()
    return time.perf_counter() - started


def _assert_linear(parse: Callable[[str], Any], build: Callable[[int], str]) -> None:
    """Fail when parse time grows much faster than the input size."""
    small_input = build(1)
    large_input = build(_GROWTH)
    small = large = float("inf")
    # Interleaved rounds, best of each, so one slow moment on a shared
    # runner does not decide the result.
    for _ in range(_ROUNDS):
        small = min(small, _timed(lambda: parse(small_input)))
        large = min(large, _timed(lambda: parse(large_input)))
    if large < _NOISE_FLOOR_SECONDS:
        return
    ratio = large / max(small, 1e-6)
    assert ratio < _MAX_GROWTH_RATIO, (
        f"{_GROWTH}x input took {ratio:.1f}x longer ({small:.3f}s -> {large:.3f}s)"
    )


def _recover(text: str) -> Any:
    return extract_tool_calls_from_response_text(text, _TOOLS)


# Each builder takes a scale factor; scale 1 is the small input.
@pytest.mark.parametrize(
    "build",
    [
        pytest.param(
            lambda k: "<function_calls><invoke " + "{" * 6_000 * k, id="open-braces"
        ),
        pytest.param(
            lambda k: "<function_calls>" + "<invoke name='x'>" * 4_000 * k,
            id="unclosed-invoke",
        ),
        pytest.param(
            lambda k: "<function_calls>" + "<invoke " * 4_000 * k, id="invoke-no-gt"
        ),
        pytest.param(
            lambda k: (
                '<function_calls><invoke name="internal_search">'
                + "<parameter name='q'>" * 4_000 * k
                + "</invoke></function_calls>"
            ),
            id="unclosed-parameter",
        ),
        pytest.param(
            lambda k: '{"a":' * 2_500 * k + "1" + "}" * 2_500 * k,
            id="deeply-nested-json",
        ),
        pytest.param(
            lambda k: "<function_calls><invoke " + "{bad}" * 5_000 * k,
            id="many-invalid",
        ),
        pytest.param(
            lambda k: ('{"a":' * 200 + "0" + "}" * 200) * 12 * k,
            id="many-deep-objects",
        ),
    ],
)
def test_tool_call_recovery_is_linear(build: Callable[[int], str]) -> None:
    _assert_linear(_recover, build)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda k: "{" * 8_000 * k, id="open-braces"),
        pytest.param(lambda k: "```{" * 6_000 * k, id="fenced-open-braces"),
        pytest.param(
            lambda k: "```json\n{" + "}```" * 6_000 * k, id="many-closing-fences"
        ),
    ],
)
def test_parse_llm_json_response_is_linear(build: Callable[[int], str]) -> None:
    _assert_linear(parse_llm_json_response, build)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda k: "(" + " " * 500 * k, id="open-paren-spaces"),
        pytest.param(lambda k: "(" + " " * 500 * k + ")", id="closed-paren-spaces"),
        pytest.param(lambda k: "( a" + " " * 500 * k + ")", id="token-then-spaces"),
        pytest.param(lambda k: "(" + " " * 12_500 * k, id="long-spaces"),
    ],
)
def test_time_filter_parse_is_linear(build: Callable[[int], str]) -> None:
    _assert_linear(_parse_time_decision, build)


def test_time_filter_pair_regex_is_linear_without_the_length_cap() -> None:
    _assert_linear(_TIME_FILTER_PAIR_RE.search, lambda k: "(" + " " * 500 * k)


def test_find_all_json_objects_keeps_nested_and_order() -> None:
    text = 'x {"name": "t", "arguments": {"q": 1}} y {bad} {"z": "}"} {"w": {}}'
    assert find_all_json_objects(text) == [
        {"name": "t", "arguments": {"q": 1}},
        {"q": 1},
        {"w": {}},
        {},
    ]


@pytest.mark.parametrize(
    "content,expected",
    [
        ('```json\n{"a": {"b": 1}}\n```', {"a": {"b": 1}}),
        ('```\n{"a": 1}\n``` then ```python\nx\n```', {"a": 1}),
        ('{"a": 1}', {"a": 1}),
        ('Sure: {"a": 1} done', {"a": 1}),
        ("no json here", None),
        ("{" * 1_000, None),
    ],
)
def test_parse_llm_json_response_cases(
    content: str, expected: dict[str, Any] | None
) -> None:
    assert parse_llm_json_response(content) == expected


def test_xml_tool_call_recovery_still_parses() -> None:
    text = (
        "<function_calls><invoke name='bogus'></invoke>"
        '<invoke name="internal_search">'
        '<parameter name="queries" string="false">["foo"]</parameter>'
        "</invoke></function_calls>"
    )
    calls = extract_tool_calls_from_response_text(text, _TOOLS)
    assert [(c.name, c.arguments) for c in calls] == [
        ("internal_search", {"queries": ["foo"]})
    ]


@pytest.mark.parametrize("depth", [100, 400])
def test_tool_calls_after_deep_and_invalid_objects_are_kept(depth: int) -> None:
    call = '{"name": "internal_search", "arguments": {"queries": ["%s"]}}'
    text = (
        '{"a":' * depth
        + "0"
        + "}" * depth
        + " {bad} " * 50
        + " ".join(call % query for query in ("foo", "bar", "baz"))
    )
    calls = extract_tool_calls_from_response_text(text, _TOOLS)
    assert [c.arguments for c in calls] == [
        {"queries": ["foo"]},
        {"queries": ["bar"]},
        {"queries": ["baz"]},
    ]
