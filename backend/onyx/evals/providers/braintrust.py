from collections.abc import Callable

from autoevals.llm import LLMClassifier
from braintrust import Eval
from braintrust import EvalCase
from braintrust import init_dataset

from onyx.configs.app_configs import BRAINTRUST_MAX_CONCURRENCY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider


quality_classifier = LLMClassifier(
    name="quality",
    prompt_template="""
    You are a customer doing a trial of the product Onyx. Onyx provides a UI for users to chat with an LLM
     and search for information, similar to ChatGPT. You think ChatGPT's answer quality is great, and
     you want to rate Onyx's response relativeto ChatGPT's response.\n
    [Question]: {{input}}\n
    [ChatGPT Answer]: {{expected}}\n
    [Onyx Answer]: {{output}}\n

    Please rate the quality of the Onyx answer relative to the ChatGPT answer on a scale of A to E:
    A: The Onyx answer is great and is as good or better than the ChatGPT answer.
    B: The Onyx answer is good and and comparable to the ChatGPT answer.
    C: The Onyx answer is fair.
    D: The Onyx answer is poor and is worse than the ChatGPT answer.
    E: The Onyx answer is terrible and is much worse than the ChatGPT answer.
    """,
    choice_scores={
        "A": 1,
        "B": 0.75,
        "C": 0.5,
        "D": 0.25,
        "E": 0,
    },
)


class BraintrustEvalProvider(EvalProvider):
    def eval(
        self,
        task: Callable[[dict[str, str]], str],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, dict[str, str]]] | None = None,
        remote_dataset_name: str | None = None,
        no_send_logs: bool = False,
    ) -> EvalationAck:
        if data is not None and remote_dataset_name is not None:
            raise ValueError("Cannot specify both data and remote_dataset_name")
        if data is None and remote_dataset_name is None:
            raise ValueError("Must specify either data or remote_dataset_name")

        if remote_dataset_name is not None:
            eval_data = init_dataset(
                project=BRAINTRUST_PROJECT, name=remote_dataset_name
            )
            Eval(
                name=BRAINTRUST_PROJECT,
                data=eval_data,
                task=task,
                scores=[],
                metadata={**configuration.model_dump()},
                max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
                no_send_logs=no_send_logs,
            )
        else:
            if data is None:
                raise ValueError(
                    "Must specify data when remote_dataset_name is not specified"
                )
            eval_cases: list[EvalCase[dict[str, str], str]] = [
                EvalCase(input=item["input"]) for item in data
            ]
            Eval(
                name=BRAINTRUST_PROJECT,
                data=eval_cases,
                task=task,
                scores=[],
                metadata={**configuration.model_dump()},
                max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
                no_send_logs=no_send_logs,
            )
        return EvalationAck(success=True)
