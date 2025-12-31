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
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


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
    ) -> EvalationAck:
        if remote_dataset_name is not None:
            raise ValueError(
                "LocalEvalProvider does not support remote datasets. "
                "Use --local-data-path with a local JSON file."
            )

        if data is None:
            raise ValueError("data is required for LocalEvalProvider")

        total = len(data)
        passed = 0
        failed = 0
        no_assertion = 0

        print(f"\n{BOLD}Running {total} evaluation(s)...{RESET}\n")
        print("=" * 60)

        for i, item in enumerate(data, 1):
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

                # Display timing trace
                if result.timings:
                    print(f"  {BOLD}Trace:{RESET}")
                    print(f"    Total: {result.timings.total_ms:.0f}ms")
                    if result.timings.llm_first_token_ms is not None:
                        print(
                            f"    First token: {result.timings.llm_first_token_ms:.0f}ms"
                        )
                    if result.timings.tool_execution_ms:
                        for (
                            tool_name,
                            duration_ms,
                        ) in result.timings.tool_execution_ms.items():
                            print(f"    {tool_name}: {duration_ms:.0f}ms")

                # Display tools called
                tools_str = (
                    ", ".join(result.tools_called) if result.tools_called else "(none)"
                )
                print(f"  Tools called: {BLUE}{tools_str}{RESET}")

                # Display assertion result
                if result.assertion_passed is None:
                    print(f"  Assertion: {YELLOW}N/A{RESET} - No assertion configured")
                    no_assertion += 1
                elif result.assertion_passed:
                    print(
                        f"  Assertion: {GREEN}PASS{RESET} - {result.assertion_details}"
                    )
                    passed += 1
                else:
                    print(f"  Assertion: {RED}FAIL{RESET} - {result.assertion_details}")
                    failed += 1

                # Display truncated answer
                answer = result.answer
                truncated_answer = answer[:200] + "..." if len(answer) > 200 else answer
                # Replace newlines for cleaner output
                truncated_answer = truncated_answer.replace("\n", " ")
                print(f"  Answer: {truncated_answer}")

            except Exception as e:
                print(f"  {RED}ERROR:{RESET} {e}")
                failed += 1
                logger.exception(f"Error running eval for input: {message}")

        # Summary
        print("\n" + "=" * 60)
        total_with_assertions = passed + failed
        if total_with_assertions > 0:
            pass_rate = (passed / total_with_assertions) * 100
            print(
                f"{BOLD}Summary:{RESET} {passed}/{total_with_assertions} passed ({pass_rate:.1f}%)"
            )
        else:
            print(f"{BOLD}Summary:{RESET} No assertions configured")

        print(f"  {GREEN}Passed:{RESET} {passed}")
        print(f"  {RED}Failed:{RESET} {failed}")
        if no_assertion > 0:
            print(f"  {YELLOW}No assertion:{RESET} {no_assertion}")
        print("=" * 60 + "\n")

        # Return success if no failures
        return EvalationAck(success=(failed == 0))
