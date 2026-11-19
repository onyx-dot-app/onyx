"""The model's cut of exec output and its full value."""

from onyx.server.features.build.sandbox.models import ExecCommandResult
from onyx.tools.tool_implementations.sandbox.models import SandboxExecResult
from onyx.tools.tool_implementations.sandbox.sandbox_tools import _exec_result


def _result(head: str, tail: str = "", omitted: int = 0) -> ExecCommandResult:
    return ExecCommandResult(
        head=head,
        tail=tail,
        omitted_chars=omitted,
        session_id=None,
        exit_code=0,
        completion="exited",
        wall_time_seconds=1.0,
        truncated=bool(omitted),
    )


def test_one_marker_counts_the_byte_cap_and_the_cut_together() -> None:
    result = _exec_result(_result("h" * 100, "t" * 100, omitted=1_000), 50)

    output = result.content.split("Output:\n", 1)[1]
    assert output == (
        "h" * 25 + "\n... [output truncated, 1150 characters omitted] ...\n" + "t" * 25
    )
    assert output.count("[output truncated") == 1
    assert "Original character count: 1200" in result.content


def test_the_card_shows_a_cut_as_truncated_and_the_full_value_only_the_byte_cap() -> (
    None
):
    cut = _exec_result(_result("o" * 100), 50)
    details, full = cut.details, cut.full_value
    assert isinstance(details, SandboxExecResult) and details.truncated
    assert isinstance(full, SandboxExecResult)
    assert (full.output, full.truncated) == ("o" * 100, False)

    capped = _exec_result(_result("h" * 10, "t" * 10, omitted=5), 50)
    assert isinstance(capped.details, SandboxExecResult)
    assert capped.details.truncated and capped.full_value is None

    whole = _exec_result(_result("o" * 10), 50)
    assert isinstance(whole.details, SandboxExecResult)
    assert not whole.details.truncated and whole.full_value is None


def test_output_at_exactly_its_budget_gives_no_full_value() -> None:
    at_budget = _exec_result(_result("h" * 30, "t" * 20), 50)
    assert isinstance(at_budget.details, SandboxExecResult)
    assert at_budget.details.output == "h" * 30 + "t" * 20
    assert not at_budget.details.truncated and at_budget.full_value is None

    over_budget = _exec_result(_result("h" * 30, "t" * 21), 50)
    assert isinstance(over_budget.full_value, SandboxExecResult)
