"""LLM output parsers must stay linear on adversarial model output."""

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

# Linear code finishes these inputs in milliseconds; the old quadratic and
# cubic scans took from several seconds to minutes.
_TIME_BOUND_SECONDS = 1.0

_TOOLS = [
    ToolDefinition(
        name="internal_search",
        description="",
        parameters={"type": "object", "properties": {"queries": {}}},
    )
]


def _assert_fast(fn: Callable[[], Any]) -> None:
    """Fail when fn runs past the bound. SIGALRM interrupts a stalled parser
    (sre and the Python loop both check signals), so a regression fails the
    test instead of hanging it."""

    def _on_timeout(_signum: int, _frame: FrameType | None) -> None:
        raise TimeoutError(f"took more than {_TIME_BOUND_SECONDS}s")

    previous_handler = signal.signal(signal.SIGALRM, _on_timeout)
    signal.setitimer(signal.ITIMER_REAL, _TIME_BOUND_SECONDS)
    started = time.perf_counter()
    try:
        fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    elapsed = time.perf_counter() - started
    assert elapsed < _TIME_BOUND_SECONDS, f"took {elapsed:.2f}s"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("<function_calls><invoke " + "{" * 50_000, id="open-braces"),
        pytest.param(
            "<function_calls>" + "<invoke name='x'>" * 30_000, id="unclosed-invoke"
        ),
        pytest.param("<function_calls>" + "<invoke " * 30_000, id="invoke-no-gt"),
        pytest.param(
            '<function_calls><invoke name="internal_search">'
            + "<parameter name='q'>" * 30_000
            + "</invoke></function_calls>",
            id="unclosed-parameter",
        ),
        pytest.param('{"a":' * 20_000 + "1" + "}" * 20_000, id="deeply-nested-json"),
        pytest.param("<function_calls><invoke " + "{bad}" * 40_000, id="many-invalid"),
        pytest.param(('{"a":' * 200 + "0" + "}" * 200) * 100, id="many-deep-objects"),
    ],
)
def test_tool_call_recovery_is_linear(text: str) -> None:
    _assert_fast(lambda: extract_tool_calls_from_response_text(text, _TOOLS))


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("{" * 64_000, id="open-braces"),
        pytest.param("```{" * 50_000, id="fenced-open-braces"),
        pytest.param("```json\n{" + "}```" * 50_000, id="many-closing-fences"),
    ],
)
def test_parse_llm_json_response_is_linear(content: str) -> None:
    _assert_fast(lambda: parse_llm_json_response(content))


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("(" + " " * 4_000, id="open-paren-spaces"),
        pytest.param("(" + " " * 4_000 + ")", id="closed-paren-spaces"),
        pytest.param("( a" + " " * 4_000 + ")", id="token-then-spaces"),
        pytest.param("(" + " " * 100_000, id="long-spaces"),
    ],
)
def test_time_filter_parse_is_linear(content: str) -> None:
    _assert_fast(lambda: _parse_time_decision(content))


def test_time_filter_pair_regex_is_linear_without_the_length_cap() -> None:
    _assert_fast(lambda: _TIME_FILTER_PAIR_RE.search("(" + " " * 4_000))


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
