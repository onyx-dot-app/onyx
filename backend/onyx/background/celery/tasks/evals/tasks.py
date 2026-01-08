from datetime import datetime
from datetime import timezone
from typing import Any

from celery import shared_task
from celery import Task

from onyx.configs.app_configs import BRAINTRUST_API_KEY
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import SCHEDULED_EVAL_DATASET_NAMES
from onyx.configs.app_configs import SCHEDULED_EVAL_PERMISSIONS_EMAIL
from onyx.configs.app_configs import SCHEDULED_EVAL_PROJECT
from onyx.configs.constants import OnyxCeleryTask
from onyx.evals.eval import run_eval
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
        configuration = EvalConfigurationOptions.model_validate(configuration_dict)
        run_eval(configuration, remote_dataset_name=configuration.dataset_name)
        logger.info("Successfully completed eval run task")

    except Exception:
        logger.error("Failed to run eval task")
        raise


@shared_task(
    name=OnyxCeleryTask.SCHEDULED_EVAL_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT * 5,  # Allow more time for multiple datasets
    bind=True,
    trail=False,
)
def scheduled_eval_task(self: Task, **kwargs: Any) -> None:
    """
    Scheduled task to run evaluations on configured datasets.
    Runs weekly on Sunday at midnight UTC.

    Configure via environment variables (with defaults):
    - SCHEDULED_EVAL_DATASET_NAMES: Comma-separated list of Braintrust dataset names
    - SCHEDULED_EVAL_PERMISSIONS_EMAIL: Email for search permissions (default: roshan@onyx.app)
    - SCHEDULED_EVAL_PROJECT: Braintrust project name
    """
    if not BRAINTRUST_API_KEY:
        logger.error("BRAINTRUST_API_KEY is not configured, cannot run scheduled evals")
        return

    if not SCHEDULED_EVAL_PROJECT:
        logger.error(
            "SCHEDULED_EVAL_PROJECT is not configured, cannot run scheduled evals"
        )
        return

    if not SCHEDULED_EVAL_DATASET_NAMES:
        logger.info("No scheduled eval datasets configured, skipping")
        return

    if not SCHEDULED_EVAL_PERMISSIONS_EMAIL:
        logger.error("SCHEDULED_EVAL_PERMISSIONS_EMAIL not configured")
        return

    project_name = SCHEDULED_EVAL_PROJECT
    dataset_names = SCHEDULED_EVAL_DATASET_NAMES
    permissions_email = SCHEDULED_EVAL_PERMISSIONS_EMAIL

    # Create a timestamp for the scheduled run
    run_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(
        f"Starting scheduled eval pipeline for project '{project_name}' "
        f"with {len(dataset_names)} dataset(s): {dataset_names}"
    )

    pipeline_start = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    for dataset_name in dataset_names:
        start_time = datetime.now(timezone.utc)
        error_message: str | None = None
        success = False

        # Create informative experiment name for scheduled runs
        experiment_name = f"{dataset_name} - {run_timestamp}"

        try:
            logger.info(
                f"Running scheduled eval for dataset: {dataset_name} "
                f"(project: {project_name})"
            )

            configuration = EvalConfigurationOptions(
                search_permissions_email=permissions_email,
                dataset_name=dataset_name,
                no_send_logs=False,
                braintrust_project=project_name,
                experiment_name=experiment_name,
            )

            result = run_eval(
                configuration=configuration,
                remote_dataset_name=dataset_name,
            )
            success = result.success
            logger.info(f"Completed eval for {dataset_name}: success={success}")

        except Exception as e:
            logger.exception(f"Failed to run scheduled eval for {dataset_name}")
            error_message = str(e)
            success = False

        end_time = datetime.now(timezone.utc)

        results.append(
            {
                "dataset_name": dataset_name,
                "success": success,
                "start_time": start_time,
                "end_time": end_time,
                "error_message": error_message,
            }
        )

    pipeline_end = datetime.now(timezone.utc)
    total_duration = (pipeline_end - pipeline_start).total_seconds()

    passed_count = sum(1 for r in results if r["success"])
    logger.info(
        f"Scheduled eval pipeline completed: {passed_count}/{len(results)} passed "
        f"in {total_duration:.1f}s"
    )
