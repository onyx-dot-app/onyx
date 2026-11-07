"""Both dataset providers preserve the same preference and legacy-input contract."""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.evals.models import EvalConfigurationOptions, EvalProvider, EvalToolResult
from onyx.evals.providers.braintrust import BraintrustEvalProvider
from onyx.evals.providers.local import LocalEvalProvider


@pytest.mark.parametrize("provider", [LocalEvalProvider, BraintrustEvalProvider])
@pytest.mark.parametrize("outer_override", [False, True])
def test_dataset_preference_reaches_task(
    provider: type[EvalProvider], outer_override: bool
) -> None:
    seen: list[dict[str, Any]] = []

    def task(value: dict[str, Any]) -> EvalToolResult:
        seen.append(value)
        return EvalToolResult(
            answer="OK", tools_called=[], tool_call_details=[], citations=[]
        )

    def braintrust_eval(**kwargs: Any) -> None:
        for case in kwargs["data"]:
            kwargs["task"](case.input)

    data: dict[str, Any] = {
        "input": {
            "message": "Question",
            "preferred_tool": "SearchTool",
            "temperature": 0.3,
        }
    }
    if outer_override:
        data["preferred_tool"] = None
    with patch("onyx.evals.providers.braintrust.Eval", side_effect=braintrust_eval):
        provider().eval(
            task,
            EvalConfigurationOptions(
                search_permissions_email="test@example.com", dataset_name="test"
            ),
            data=[data],
        )
    assert len(seen) == 1
    assert seen[0]["preferred_tool"] == (None if outer_override else "SearchTool")
    assert seen[0]["temperature"] == 0.3


@pytest.mark.parametrize("provider", [LocalEvalProvider, BraintrustEvalProvider])
@pytest.mark.parametrize("nested", [False, True])
def test_dataset_legacy_forcing_is_rejected_before_task(
    provider: type[EvalProvider], nested: bool
) -> None:
    input_value: dict[str, Any] = {"message": "Question"}
    data: dict[str, Any] = {"input": input_value}
    (input_value if nested else data)["force_tools"] = ["SearchTool"]
    with patch("onyx.evals.providers.braintrust.Eval") as remote:
        with pytest.raises(ValueError, match="force_tools is no longer supported"):
            provider().eval(
                lambda _: pytest.fail("Legacy input reached task"),
                EvalConfigurationOptions(
                    search_permissions_email="test@example.com", dataset_name="test"
                ),
                data=[data],
            )
        remote.assert_not_called()
