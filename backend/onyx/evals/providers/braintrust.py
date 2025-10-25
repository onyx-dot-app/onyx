from collections.abc import Callable
from typing import Any

from braintrust import Eval
from braintrust import EvalCase
from braintrust import init_dataset
from sqlalchemy.orm import Session

from onyx.configs.app_configs import BRAINTRUST_MAX_CONCURRENCY
from onyx.configs.app_configs import BRAINTRUST_PROJECT
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.llm.override_models import LLMOverride


class BraintrustEvalProvider(EvalProvider):
    def eval(
        self,
        task: Callable[[dict[str, str], LLMOverride | None], str],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, dict[str, str]]] | None = None,
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
                eval_data = [EvalCase(input=item["input"]) for item in data]

        # Get the LLMs from the configuration
        engine = get_sqlalchemy_engine()
        with Session(engine) as db_session:
            full_configuration = configuration.get_configuration(db_session)
            llms = full_configuration.llms

        # If no LLMs are specified, run with default
        if not llms:
            Eval(
                name=BRAINTRUST_PROJECT,
                data=eval_data,  # type: ignore[arg-type]
                task=lambda eval_input: task(eval_input, None),
                scores=[],
                metadata={**configuration.model_dump()},
                max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
                no_send_logs=configuration.no_send_logs,
            )
        else:
            # Run an eval for each LLM in sequence
            for llm in llms:
                experiment_name = f"{llm.model_provider}_{llm.model_version}"
                Eval(
                    name=BRAINTRUST_PROJECT,
                    experiment=experiment_name,
                    data=eval_data,  # type: ignore[arg-type]
                    task=lambda eval_input, llm_override=llm: task(
                        eval_input, llm_override
                    ),
                    scores=[],
                    metadata={
                        **configuration.model_dump(),
                        "model_provider": llm.model_provider,
                        "model_version": llm.model_version,
                    },
                    max_concurrency=BRAINTRUST_MAX_CONCURRENCY,
                    no_send_logs=configuration.no_send_logs,
                )

        return EvalationAck(success=True)
