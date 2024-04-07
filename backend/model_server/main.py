import os

import torch
import uvicorn
from fastapi import FastAPI
from transformers import logging as transformer_logging  # type:ignore

from danswer import __version__
from danswer.configs.app_configs import MODEL_SERVER_ALLOWED_HOST
from danswer.configs.app_configs import MODEL_SERVER_PORT
from danswer.utils.logger import setup_logger
from model_server.custom_models import router as custom_models_router
from model_server.custom_models import warm_up_intent_model
from model_server.encoders import router as encoders_router
from model_server.encoders import warm_up_cross_encoders
from shared_configs.nlp_model_configs import INDEXING_ONLY
from shared_configs.nlp_model_configs import MIN_THREADS_ML_MODELS

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

transformer_logging.set_verbosity_error()

logger = setup_logger()


def get_model_app() -> FastAPI:
    application = FastAPI(title="Danswer Model Server", version=__version__)

    application.include_router(encoders_router)
    application.include_router(custom_models_router)

    @application.on_event("startup")
    def startup_event() -> None:
        if torch.cuda.is_available():
            logger.info("GPU is available")
        else:
            logger.info("GPU is not available")

        torch.set_num_threads(max(MIN_THREADS_ML_MODELS, torch.get_num_threads()))
        logger.info(f"Torch Threads: {torch.get_num_threads()}")

        if not INDEXING_ONLY:
            warm_up_cross_encoders()
            warm_up_intent_model()
        else:
            logger.info("This model server should only run document indexing.")

    return application


app = get_model_app()


if __name__ == "__main__":
    logger.info(
        f"Starting Danswer Model Server on http://{MODEL_SERVER_ALLOWED_HOST}:{str(MODEL_SERVER_PORT)}/"
    )
    logger.info(f"Model Server Version: {__version__}")
    uvicorn.run(app, host=MODEL_SERVER_ALLOWED_HOST, port=MODEL_SERVER_PORT)
