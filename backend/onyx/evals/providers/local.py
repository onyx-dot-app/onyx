"""
Local eval provider that runs evaluations and outputs results to the CLI.
No external dependencies like Braintrust required.
"""

from collections.abc import Callable
from typing import Any

from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.evals.models import EvalToolResult
from onyx.evals.models import MultiTurnEvalResult
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


def _display_single_turn_result(
    result: EvalToolResult,
    passed_count: list[int],
    failed_count: list[int],
    no_assertion_count: list[int],
) -> None:
    """Display results for a single turn and update counters."""
    # Display timing trace
    if result.timings:
        print(f"  {BOLD}Trace:{RESET}")
        print(f"    Total: {result.timings.total_ms:.0f}ms")
        if result.timings.llm_first_token_ms is not None:
            print(f"    First token: {result.timings.llm_first_token_ms:.0f}ms")
        if result.timings.tool_execution_ms:
            for tool_name, duration_ms in result.timings.tool_execution_ms.items():
                print(f"    {tool_name}: {duration_ms:.0f}ms")

    # Display tools called
    tools_str = ", ".join(result.tools_called) if result.tools_called else "(none)"
    print(f"  Tools called: {BLUE}{tools_str}{RESET}")

    # Display assertion result
    if result.assertion_passed is None:
        print(f"  Assertion: {YELLOW}N/A{RESET} - No assertion configured")
        no_assertion_count[0] += 1
    elif result.assertion_passed:
        print(f"  Assertion: {GREEN}PASS{RESET} - {result.assertion_details}")
        passed_count[0] += 1
    else:
        print(f"  Assertion: {RED}FAIL{RESET} - {result.assertion_details}")
        failed_count[0] += 1

    # Display truncated answer
    answer = result.answer
    truncated_answer = answer[:200] + "..." if len(answer) > 200 else answer
    truncated_answer = truncated_answer.replace("\n", " ")
    print(f"  Answer: {truncated_answer}")


class LocalEvalProvider(EvalProvider):
    """
    Eval provider that runs evaluations locally and prints results to the CLI.
    Does not require Braintrust or any external service.
    """

    def eval(
        self,
        task: Callable[[dict[str, Any]], EvalToolResult],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, Any]] | None = None,
        remote_dataset_name: str | None = None,
        multi_turn_task: Callable[[dict[str, Any]], MultiTurnEvalResult] | None = None,
    ) -> EvalationAck:
        if remote_dataset_name is not None:
            raise ValueError(
                "LocalEvalProvider does not support remote datasets. "
                "Use --local-data-path with a local JSON file."
            )

        if data is None:
            raise ValueError("data is required for LocalEvalProvider")

        total = len(data)
        # Use lists to allow mutation in helper function
        passed = [0]
        failed = [0]
        no_assertion = [0]

        print(f"\n{BOLD}Running {total} evaluation(s)...{RESET}\n")
        print("=" * 60)

        for i, item in enumerate(data, 1):
            input_data = item.get("input", {})

            # Check if this is a multi-turn eval (has 'messages' array)
            if "messages" in input_data:
                self._run_multi_turn_eval(
                    i, total, item, multi_turn_task, passed, failed, no_assertion
                )
            else:
                self._run_single_turn_eval(
                    i, total, item, task, passed, failed, no_assertion
                )

        # Summary
        print("\n" + "=" * 60)
        total_with_assertions = passed[0] + failed[0]
        if total_with_assertions > 0:
            pass_rate = (passed[0] / total_with_assertions) * 100
            print(
                f"{BOLD}Summary:{RESET} {passed[0]}/{total_with_assertions} passed ({pass_rate:.1f}%)"
            )
        else:
            print(f"{BOLD}Summary:{RESET} No assertions configured")

        print(f"  {GREEN}Passed:{RESET} {passed[0]}")
        print(f"  {RED}Failed:{RESET} {failed[0]}")
        if no_assertion[0] > 0:
            print(f"  {YELLOW}No assertion:{RESET} {no_assertion[0]}")
        print("=" * 60 + "\n")

        # Return success if no failures
        return EvalationAck(success=(failed[0] == 0))

    def _run_single_turn_eval(
        self,
        i: int,
        total: int,
        item: dict[str, Any],
        task: Callable[[dict[str, Any]], EvalToolResult],
        passed: list[int],
        failed: list[int],
        no_assertion: list[int],
    ) -> None:
        """Run a single-turn evaluation."""
        # Build input with tool and model config
        eval_input = {
            **item.get("input", {}),
            # Tool configuration
            "force_tools": item.get("force_tools", []),
            "expected_tools": item.get("expected_tools", []),
            "require_all_tools": item.get("require_all_tools", False),
            # Model configuration
            "model": item.get("model"),
            "model_provider": item.get("model_provider"),
            "temperature": item.get("temperature"),
        }

        message = eval_input.get("message", "(no message)")
        truncated_message = message[:50] + "..." if len(message) > 50 else message

        # Show model if specified
        model_info = ""
        if item.get("model"):
            model_info = f" [{item.get('model')}]"

        print(f'\n{BOLD}[{i}/{total}]{RESET} "{truncated_message}"{model_info}')

        try:
            result = task(eval_input)
            _display_single_turn_result(result, passed, failed, no_assertion)
        except Exception as e:
            print(f"  {RED}ERROR:{RESET} {e}")
            failed[0] += 1
            logger.exception(f"Error running eval for input: {message}")

    def _run_multi_turn_eval(
        self,
        i: int,
        total: int,
        item: dict[str, Any],
        multi_turn_task: Callable[[dict[str, Any]], MultiTurnEvalResult] | None,
        passed: list[int],
        failed: list[int],
        no_assertion: list[int],
    ) -> None:
        """Run a multi-turn evaluation."""
        if multi_turn_task is None:
            print(
                f"\n{BOLD}[{i}/{total}]{RESET} {RED}ERROR:{RESET} Multi-turn task not configured"
            )
            failed[0] += 1
            return

        input_data = item.get("input", {})
        messages = input_data.get("messages", [])
        num_turns = len(messages)

        # Show first message as preview
        first_msg = (
            messages[0].get("message", "(no message)") if messages else "(no messages)"
        )
        truncated_first = first_msg[:40] + "..." if len(first_msg) > 40 else first_msg

        print(f"\n{BOLD}[{i}/{total}] Multi-turn ({num_turns} turns){RESET}")
        print(f'  First: "{truncated_first}"')

        try:
            # Pass the full input with messages
            eval_input = {**input_data}
            result = multi_turn_task(eval_input)

            # Display each turn's result
            for turn_idx, turn_result in enumerate(result.turn_results):
                turn_msg = messages[turn_idx].get("message", "")
                truncated_turn = (
                    turn_msg[:40] + "..." if len(turn_msg) > 40 else turn_msg
                )
                print(f'\n  {DIM}Turn {turn_idx + 1}:{RESET} "{truncated_turn}"')
                _display_single_turn_result(turn_result, passed, failed, no_assertion)

            # Show multi-turn summary
            status = (
                f"{GREEN}ALL PASSED{RESET}"
                if result.all_passed
                else f"{RED}SOME FAILED{RESET}"
            )
            print(
                f"\n  {BOLD}Multi-turn result:{RESET} {status} ({result.pass_count}/{result.total_turns} turns passed)"
            )

        except Exception as e:
            print(f"  {RED}ERROR:{RESET} {e}")
            failed[0] += 1
            logger.exception(f"Error running multi-turn eval: {first_msg}")
