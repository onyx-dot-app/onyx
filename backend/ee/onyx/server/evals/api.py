from fastapi import APIRouter
from fastapi import Depends

from ee.onyx.auth.users import current_cloud_superuser
from onyx.background.celery.apps.client import celery_app as client_app
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import User
from onyx.evals.models import EvalConfigurationOptions
from onyx.server.evals.models import EvalRunAck
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/evals")


@router.post("/eval_run", response_model=EvalRunAck)
def eval_run(
    request: EvalConfigurationOptions,
    user: User = Depends(current_cloud_superuser),
) -> EvalRunAck:
    """
    Run an evaluation with the given message and optional dataset.
    This endpoint requires a valid API key for authentication.
    """
    client_app.send_task(
        OnyxCeleryTask.EVAL_RUN_TASK,
        kwargs={
            "configuration_dict": request.model_dump(),
        },
    )
    return EvalRunAck(success=True)
