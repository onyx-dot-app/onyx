from collections.abc import Callable
from typing import Any

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
from onyx.utils.logger import setup_logger

logger = setup_logger()


def tool_assertion_scorer(
    input: dict[str, Any], output: EvalToolResult, expected: EvalToolResult | None
) -> Score:
    """
    Scorer that checks if tool assertions passed.

    Args:
        input: The input data for the evaluation case.
        output: The actual output from the task.
        expected: The expected output (unused for this scorer).

    Returns:
        Score with value 1.0 if passed or no assertions, 0.0 if failed.
    """
    # input and expected are unused but required by Braintrust scorer signature
    _ = input, expected
    if output.assertion_passed is None:
        # No assertions configured - return passing score
        return Score(
            name="tool_assertion",
            score=1.0,
            metadata={
                "tools_called": output.tools_called,
                "tools_called_count": len(output.tools_called),
                "assertion_configured": False,
            },
        )

    return Score(
        name="tool_assertion",
        score=1.0 if output.assertion_passed else 0.0,
        metadata={
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
    ) -> EvalationAck:
        if data is not None and remote_dataset_name is not None:
            raise ValueError("Cannot specify both data and remote_dataset_name")
        if data is None and remote_dataset_name is None:
            raise ValueError("Must specify either data or remote_dataset_name")

        eval_data: Any = None
        if remote_dataset_name is not None:
            eval_data = init_dataset(
                project=BRAINTRUST_PROJECT, name=remote_dataset_name
            )
        else:
            if data:
                eval_data = [
                    EvalCase(
                        input={
                            **item.get("input", {}),
                            # Pass through per-test tool configuration
                            "force_tools": item.get("force_tools", []),
                            "expected_tools": item.get("expected_tools", []),
                            "require_all_tools": item.get("require_all_tools", False),
                        },
                        expected=item.get("expected"),
                    )
                    for item in data
                ]

        metadata = configuration.model_dump()

        Eval(
            name=BRAINTRUST_PROJECT,
            data=eval_data,
            task=task,
            scores=[tool_assertion_scorer],
            metadata=metadata,
            max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
            no_send_logs=configuration.no_send_logs,
        )
        return EvalationAck(success=True)
