import logging
import os
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
import torch
import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from transformers import logging as transformer_logging  # type:ignore

from model_server.custom_models import router as custom_models_router
from model_server.custom_models import warm_up_information_content_model
from model_server.custom_models import warm_up_intent_model
from model_server.encoders import router as encoders_router
from model_server.management_endpoints import router as management_router
from model_server.utils import get_gpu_type
from onyx import __version__
from onyx.utils.logger import setup_logger
from onyx.utils.logger import setup_uvicorn_logger
from onyx.utils.middleware import add_onyx_request_id_middleware
from onyx.utils.middleware import add_onyx_tenant_id_middleware
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import MIN_THREADS_ML_MODELS
from shared_configs.configs import MODEL_SERVER_ALLOWED_HOST
from shared_configs.configs import MODEL_SERVER_PORT
from shared_configs.configs import SENTRY_DSN
from shared_configs.configs import SKIP_WARM_UP

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

HF_CACHE_PATH = Path(".cache/huggingface")
TEMP_HF_CACHE_PATH = Path(".cache/temp_huggingface")

transformer_logging.set_verbosity_error()

logger = setup_logger()

file_handlers = [
    h for h in logger.logger.handlers if isinstance(h, logging.FileHandler)
]

setup_uvicorn_logger(shared_file_handlers=file_handlers)


def _move_files_recursively(source: Path, dest: Path, overwrite: bool = False) -> None:
    """
    This moves the files from the temp huggingface cache to the huggingface cache

    We have to move each file individually because the directories might
    have the same name but not the same contents and we dont want to remove
    the files in the existing huggingface cache that don't exist in the temp
    huggingface cache.
    """

    for item in source.iterdir():
        target_path = dest / item.relative_to(source)
        if item.is_dir():
            _move_files_recursively(item, target_path, overwrite)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() and not overwrite:
                continue
            shutil.move(str(item), str(target_path))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    gpu_type = get_gpu_type()
    logger.notice(f"Torch GPU Detection: gpu_type={gpu_type}")

    app.state.gpu_type = gpu_type

    try:
        if TEMP_HF_CACHE_PATH.is_dir():
            logger.notice("Moving contents of temp_huggingface to huggingface cache.")
            _move_files_recursively(TEMP_HF_CACHE_PATH, HF_CACHE_PATH)
            shutil.rmtree(TEMP_HF_CACHE_PATH, ignore_errors=True)
            logger.notice("Moved contents of temp_huggingface to huggingface cache.")
    except Exception as e:
        logger.warning(
            f"Error moving contents of temp_huggingface to huggingface cache: {e}. "
            "This is not a critical error and the model server will continue to run."
        )

    torch.set_num_threads(max(MIN_THREADS_ML_MODELS, torch.get_num_threads()))
    logger.notice(f"Torch Threads: {torch.get_num_threads()}")

    if not SKIP_WARM_UP:
        if not INDEXING_ONLY:
            logger.notice("Warming up intent model for inference model server")
            warm_up_intent_model()
        else:
            logger.notice(
                "Warming up content information model for indexing model server"
            )
            warm_up_information_content_model()
    else:
        logger.notice("Skipping model warmup due to SKIP_WARM_UP=true")

    yield


def get_model_app() -> FastAPI:
    application = FastAPI(
        title="Onyx Model Server", version=__version__, lifespan=lifespan
    )
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.1,
        )
        logger.info("Sentry initialized")
    else:
        logger.debug("Sentry DSN not provided, skipping Sentry initialization")

    application.include_router(management_router)
    application.include_router(encoders_router)
    application.include_router(custom_models_router)

    request_id_prefix = "INF"
    if INDEXING_ONLY:
        request_id_prefix = "IDX"

    add_onyx_tenant_id_middleware(application, logger)
    add_onyx_request_id_middleware(application, request_id_prefix, logger)

    # Initialize and instrument the app
    Instrumentator().instrument(application).expose(application)

    return application


app = get_model_app()


if __name__ == "__main__":
    logger.notice(
        f"Starting Onyx Model Server on http://{MODEL_SERVER_ALLOWED_HOST}:{str(MODEL_SERVER_PORT)}/"
    )
    logger.notice(f"Model Server Version: {__version__}")
    uvicorn.run(app, host=MODEL_SERVER_ALLOWED_HOST, port=MODEL_SERVER_PORT)
