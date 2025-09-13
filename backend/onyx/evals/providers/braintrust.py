from collections.abc import Callable
from typing import Any

from braintrust import Eval

from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.evals.models import EvaluationResult


class BraintrustEvalProvider(EvalProvider):
    def eval(
        self, configuration: EvalConfigurationOptions, task: Callable, data: Any
    ) -> EvaluationResult:
        Eval(
            name=BRAINTRUST_PROJECT,
            data=data,
            task=task,
            scores=[],
            metadata={**configuration.model_dump()},
            max_concurrency=1,
        )
        return EvaluationResult(success=True)
