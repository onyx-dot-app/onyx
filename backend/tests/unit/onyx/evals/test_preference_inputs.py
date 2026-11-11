"""Both dataset providers preserve the same preference and legacy-input contract."""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.evals.models import (
    EvalConfigurationOptions,
    EvalProvider,
    EvalToolResult,
    MultiTurnEvalResult,
)
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
            "force_tools": [],
            "temperature": 0.3,
        }
    }
    data["force_tools"] = []
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
@pytest.mark.parametrize("location", ["outer", "input", "message"])
@pytest.mark.parametrize("multi_turn", [False, True])
def test_dataset_legacy_forcing_is_rejected_before_task(
    provider: type[EvalProvider], location: str, multi_turn: bool
) -> None:
    input_value: dict[str, Any] = {"message": "Question"}
    data: dict[str, Any] = {"input": input_value}
    message: dict[str, Any] = {"message": "Question"}
    if multi_turn or location == "message":
        input_value = {"messages": [message]}
        data["input"] = input_value
    target: dict[str, Any] = data if location == "outer" else input_value
    if location == "message":
        target = message
    target["force_tools"] = ["SearchTool"]
    with patch("onyx.evals.providers.braintrust.Eval") as remote:
        with pytest.raises(ValueError, match="force_tools is no longer supported"):
            provider().eval(
                lambda _: pytest.fail("Legacy input reached task"),
                EvalConfigurationOptions(
                    search_permissions_email="test@example.com", dataset_name="test"
                ),
                data=[{"input": {"message": "Valid first case"}}, data],
            )
        remote.assert_not_called()


@pytest.mark.parametrize("location", ["input", "message"])
def test_remote_dataset_rejects_forcing_before_dispatch(location: str) -> None:
    value: dict[str, Any] = {"messages": [{"message": "Question"}]}
    target: dict[str, Any] = value if location == "input" else value["messages"][0]
    target["force_tools"] = ["SearchTool"]

    def remote_eval(**kwargs: Any) -> None:
        kwargs["task"](value)

    with (
        patch("onyx.evals.providers.braintrust.init_dataset"),
        patch("onyx.evals.providers.braintrust.Eval", side_effect=remote_eval),
        pytest.raises(ValueError, match="force_tools is no longer supported"),
    ):
        BraintrustEvalProvider().eval(
            lambda _: pytest.fail("Legacy input reached task"),
            EvalConfigurationOptions(
                search_permissions_email="test@example.com", dataset_name="test"
            ),
            remote_dataset_name="remote",
            multi_turn_task=lambda _: pytest.fail(
                "Legacy input reached multi-turn task"
            ),
        )


@pytest.mark.parametrize("provider", [LocalEvalProvider, BraintrustEvalProvider])
def test_multiturn_dataset_preserves_preferences_and_outer_overrides(
    provider: type[EvalProvider],
) -> None:
    seen: list[dict[str, Any]] = []
    value = {
        "messages": [
            {"message": "Question", "preferred_tool": "SearchTool"},
            {
                "message": "Follow-up",
                "temperature": 0.0,
                "preferred_tool": None,
                "expected_tools": [],
                "require_all_tools": False,
            },
        ],
        "temperature": 0.2,
        "preferred_tool": "WebSearchTool",
        "expected_tools": ["SearchTool"],
        "require_all_tools": True,
        "model": "test-model",
        "model_provider": "openai",
    }

    def task(data: dict[str, Any]) -> MultiTurnEvalResult:
        seen.append(data)
        return MultiTurnEvalResult(
            turn_results=[], all_passed=True, pass_count=0, fail_count=0, total_turns=0
        )

    def remote_eval(**kwargs: Any) -> None:
        for case in kwargs["data"]:
            kwargs["task"](case.input)

    with patch("onyx.evals.providers.braintrust.Eval", side_effect=remote_eval):
        provider().eval(
            lambda _: pytest.fail("Multi-turn data reached single-turn task"),
            EvalConfigurationOptions(
                search_permissions_email="test@example.com", dataset_name="test"
            ),
            data=[{"input": value, "temperature": 0.4}],
            multi_turn_task=task,
        )
    assert len(seen) == 1
    assert seen[0]["messages"] == [
        {
            "message": "Question",
            "preferred_tool": "SearchTool",
            "temperature": 0.4,
            "expected_tools": ["SearchTool"],
            "require_all_tools": True,
            "model": "test-model",
            "model_provider": "openai",
        },
        {
            "message": "Follow-up",
            "preferred_tool": None,
            "temperature": 0.0,
            "expected_tools": [],
            "require_all_tools": False,
            "model": "test-model",
            "model_provider": "openai",
        },
    ]
    assert value["messages"][0] == {
        "message": "Question",
        "preferred_tool": "SearchTool",
    }


@pytest.mark.parametrize(
    "multi_turn,per_message", [(False, False), (True, False), (True, True)]
)
def test_task_entry_rejects_forcing_before_database_access(
    multi_turn: bool, per_message: bool
) -> None:
    from onyx.evals.eval import (
        _get_answer_with_tools,
        _get_multi_turn_answer_with_tools,
    )

    value: dict[str, Any] = {"message": "Question"}
    if multi_turn:
        value = {"messages": [{"message": "Question"}]}
    target: dict[str, Any] = (
        value["messages"][0] if multi_turn and per_message else value
    )
    target["force_tools"] = ["SearchTool"]
    task = _get_multi_turn_answer_with_tools if multi_turn else _get_answer_with_tools
    with patch("onyx.evals.eval.get_sqlalchemy_engine") as database:
        with pytest.raises(ValueError, match="force_tools is no longer supported"):
            task(
                value,
                EvalConfigurationOptions(
                    search_permissions_email="test@example.com", dataset_name="test"
                ),
            )
        database.assert_not_called()


@pytest.mark.parametrize("provider", [LocalEvalProvider, BraintrustEvalProvider])
def test_later_unknown_preference_rejects_dataset_before_tasks(
    provider: type[EvalProvider],
) -> None:
    with patch("onyx.evals.providers.braintrust.Eval") as remote:
        with pytest.raises(ValueError, match="Unknown preferred tool: typo"):
            provider().eval(
                lambda _: pytest.fail("Invalid dataset reached task"),
                EvalConfigurationOptions(
                    search_permissions_email="test@example.com", dataset_name="test"
                ),
                data=[
                    {"input": {"message": "Valid first case"}},
                    {
                        "input": {
                            "messages": [
                                {"message": "Valid first turn"},
                                {
                                    "message": "Invalid later turn",
                                    "preferred_tool": "typo",
                                },
                            ]
                        }
                    },
                ],
            )
        remote.assert_not_called()


def test_later_unknown_preference_rejects_task_before_database_access() -> None:
    from onyx.evals.eval import _get_multi_turn_answer_with_tools

    with patch("onyx.evals.eval.get_sqlalchemy_engine") as database:
        with pytest.raises(ValueError, match="Unknown preferred tool: typo"):
            _get_multi_turn_answer_with_tools(
                {
                    "messages": [
                        {"message": "Valid first turn"},
                        {"message": "Invalid later turn", "preferred_tool": "typo"},
                    ]
                },
                EvalConfigurationOptions(
                    search_permissions_email="test@example.com", dataset_name="test"
                ),
            )
        database.assert_not_called()
