from collections.abc import Callable
from typing import Any
from typing import Union

from braintrust import Eval
from braintrust import EvalCase
from braintrust import init_dataset
from braintrust import Score

from onyx.configs.app_configs import BRAINTRUST_MAX_CONCURRENCY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.evals.models import EvalToolResult
from onyx.evals.models import MultiTurnEvalResult
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Union type for both single and multi-turn results
EvalResult = Union[EvalToolResult, MultiTurnEvalResult]


def tool_assertion_scorer(
    input: dict[str, Any], output: EvalResult, expected: EvalResult | None
) -> Score:
    """
    Scorer that checks if tool assertions passed.

    Handles both single-turn (EvalToolResult) and multi-turn (MultiTurnEvalResult) outputs.

    Args:
        input: The input data for the evaluation case.
        output: The actual output from the task.
        expected: The expected output (unused for this scorer).

    Returns:
        Score with value 1.0 if passed or no assertions, 0.0 if failed.
    """
    # input and expected are unused but required by Braintrust scorer signature
    _ = input, expected

    # Handle multi-turn results
    if isinstance(output, MultiTurnEvalResult):
        # Calculate score based on pass rate
        if output.total_turns == 0:
            score = 1.0
        else:
            # Score is the ratio of passed assertions
            assertions_evaluated = output.pass_count + output.fail_count
            if assertions_evaluated == 0:
                score = 1.0  # No assertions configured
            else:
                score = output.pass_count / assertions_evaluated

        return Score(
            name="tool_assertion",
            score=score,
            metadata={
                "is_multi_turn": True,
                "total_turns": output.total_turns,
                "pass_count": output.pass_count,
                "fail_count": output.fail_count,
                "all_passed": output.all_passed,
                "turn_details": [
                    {
                        "tools_called": r.tools_called,
                        "assertion_passed": r.assertion_passed,
                        "assertion_details": r.assertion_details,
                    }
                    for r in output.turn_results
                ],
            },
        )

    # Handle single-turn results (EvalToolResult)
    if output.assertion_passed is None:
        # No assertions configured - return passing score
        return Score(
            name="tool_assertion",
            score=1.0,
            metadata={
                "is_multi_turn": False,
                "tools_called": output.tools_called,
                "tools_called_count": len(output.tools_called),
                "assertion_configured": False,
            },
        )

    return Score(
        name="tool_assertion",
        score=1.0 if output.assertion_passed else 0.0,
        metadata={
            "is_multi_turn": False,
            "tools_called": output.tools_called,
            "tools_called_count": len(output.tools_called),
            "assertion_passed": output.assertion_passed,
            "assertion_details": output.assertion_details,
            "tool_call_details": output.tool_call_details,
        },
    )


class BraintrustEvalProvider(EvalProvider):
    def eval(
        self,
        task: Callable[[dict[str, Any]], EvalToolResult],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, Any]] | None = None,
        remote_dataset_name: str | None = None,
        multi_turn_task: Callable[[dict[str, Any]], MultiTurnEvalResult] | None = None,
    ) -> EvalationAck:
        if data is not None and remote_dataset_name is not None:
            raise ValueError("Cannot specify both data and remote_dataset_name")
        if data is None and remote_dataset_name is None:
            raise ValueError("Must specify either data or remote_dataset_name")

        # Create a wrapper task that dispatches to the appropriate handler
        def dispatch_task(eval_input: dict[str, Any]) -> EvalResult:
            if "messages" in eval_input and multi_turn_task is not None:
                return multi_turn_task(eval_input)
            return task(eval_input)

        project_name = configuration.braintrust_project or BRAINTRUST_PROJECT
        experiment_name = configuration.experiment_name

        eval_data: Any = None
        if remote_dataset_name is not None:
            eval_data = init_dataset(project=project_name, name=remote_dataset_name)
        else:
            if data:
                eval_data = [
                    EvalCase(
                        input={
                            **item.get("input", {}),
                            # Pass through per-test tool configuration (for single-turn)
                            "force_tools": item.get("force_tools", []),
                            "expected_tools": item.get("expected_tools", []),
                            "require_all_tools": item.get("require_all_tools", False),
                            # Pass through per-test model configuration
                            "model": item.get("model"),
                            "model_provider": item.get("model_provider"),
                            "temperature": item.get("temperature"),
                        },
                        expected=item.get("expected"),
                    )
                    for item in data
                ]

        metadata = configuration.model_dump()

        Eval(  # type: ignore[misc]
            name=project_name,
            experiment_name=experiment_name,
            data=eval_data,
            task=dispatch_task,
            scores=[tool_assertion_scorer],
            metadata=metadata,
            max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
            no_send_logs=configuration.no_send_logs,
        )
        return EvalationAck(success=True)
