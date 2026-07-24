"""Tests for the linear-time (RE2) regex shim.

The whole point of routing untrusted/LLM-facing patterns through RE2 is that
matching is linear-time and cannot catastrophically backtrack (ReDoS). These
tests confirm RE2 is active and that a classically pathological pattern resolves
instantly under it.
"""

import time

import pytest

from onyx.utils.regex_engine import compile_linear
from onyx.utils.regex_engine import USING_RE2


def test_re2_is_active() -> None:
    """google-re2 is a declared dependency, so the shim must use RE2 (not the
    stdlib fallback). If this fails, the prebuilt wheel didn't install and ReDoS
    protection silently degraded."""
    assert USING_RE2 is True


def test_compile_linear_basic_api() -> None:
    pattern = compile_linear(r"([\[【［]\d+(?:, ?\d+)*[\]】］])")
    matches = list(pattern.finditer("see [1] and [2, 3]"))
    assert [m.group() for m in matches] == ["[1]", "[2, 3]"]
    assert pattern.search("nope") is None
    assert pattern.search("[42]") is not None


@pytest.mark.skipif(
    not USING_RE2, reason="ReDoS-immunity guarantee only holds under the RE2 engine"
)
def test_catastrophic_backtracking_pattern_is_linear() -> None:
    """`(a+)+$` is the textbook catastrophic-backtracking pattern: against a long
    run of 'a' followed by a non-matching char, a backtracking engine takes
    exponential time. RE2 resolves it in microseconds."""
    pattern = compile_linear(r"(a+)+$")
    hostile = "a" * 60 + "!"  # would pin a CPU under stdlib `re`

    start = time.monotonic()
    result = pattern.search(hostile)
    elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 1.0


def test_fallback_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """When google-re2 is unavailable, compile_linear falls back to stdlib re and
    warns exactly once (deferred to first use, not at import time)."""
    import re

    from onyx.utils import regex_engine

    monkeypatch.setattr(regex_engine, "_re2", None)
    monkeypatch.setattr(regex_engine, "_fallback_warned", False)
    warnings: list[str] = []
    monkeypatch.setattr(
        regex_engine.logger, "warning", lambda msg, *_a, **_k: warnings.append(msg)
    )

    first = regex_engine.compile_linear(r"\d+")
    second = regex_engine.compile_linear(r"\w+")

    assert isinstance(first, re.Pattern)
    assert isinstance(second, re.Pattern)
    assert len(warnings) == 1  # warned once, not per call and not at import
