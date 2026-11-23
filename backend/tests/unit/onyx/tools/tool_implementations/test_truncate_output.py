"""truncate_output and cut_middle keep a head and a tail and log only lengths."""

from unittest.mock import MagicMock

import pytest

from onyx.tools.tool_implementations import utils
from onyx.tools.tool_implementations.utils import cut_middle, truncate_output


def test_cut_middle_counts_every_omitted_character_in_one_marker() -> None:
    assert cut_middle("h" * 50, "t" * 50, 30, omitted=7) == (
        "h" * 15 + "\n... [output truncated, 77 characters omitted] ...\n" + "t" * 15
    )
    # A short side leaves the rest of the budget to the other.
    assert cut_middle("hh", "t" * 50, 10, omitted=3) == (
        "hh\n... [output truncated, 45 characters omitted] ...\n" + "t" * 8
    )
    # With nothing omitted, a text that fits stays whole.
    assert cut_middle("head", "tail", 8) == "headtail"


def test_the_debug_log_holds_lengths_not_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(utils, "logger", logger)

    truncate_output("SECRET" * 100, 100, keep_tail=True)

    logged = " ".join(str(arg) for call in logger.mock_calls for arg in call.args)
    assert "SECRET" not in logged
    assert "500" in logged
