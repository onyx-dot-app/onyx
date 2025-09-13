import os
from typing import Any

import braintrust
from celery import shared_task
from celery import Task

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.evals.eval import eval
from onyx.evals.models import EvalConfigurationOptions
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.EVAL_RUN_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def eval_run_task(
    self: Task,
    *,
    configuration_dict: dict[str, Any],
) -> None:
    """Background task to run an evaluation with the given configuration"""
    try:
        # Convert the configuration dict back to EvalConfigurationOptions
        configuration = EvalConfigurationOptions.model_validate(configuration_dict)

        # Initialize the Braintrust dataset
        dataset = braintrust.init_dataset(
            project=os.environ["BRAINTRUST_PROJECT"], name=configuration.dataset_name
        )

        # Run the evaluation
        eval(dataset, configuration)

        logger.info("Successfully completed eval run task")

    except Exception as e:
        logger.error(f"Failed to run eval task: {str(e)}")
        raise
