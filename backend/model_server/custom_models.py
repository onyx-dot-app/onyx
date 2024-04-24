from typing import Optional

import numpy as np
import tensorflow as tf  # type: ignore
from fastapi import APIRouter
from transformers import AutoTokenizer  # type: ignore
from transformers import TFDistilBertForSequenceClassification

from model_server.constants import MODEL_WARM_UP_STRING
from model_server.utils import simple_log_function_time
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import INTENT_MODEL_CONTEXT_SIZE
from shared_configs.configs import INTENT_MODEL_VERSION
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse


router = APIRouter(prefix="/custom")

_INTENT_TOKENIZER: Optional[AutoTokenizer] = None
_INTENT_MODEL: Optional[TFDistilBertForSequenceClassification] = None


def get_intent_model_tokenizer(
    model_name: str = INTENT_MODEL_VERSION,
) -> "AutoTokenizer":
    global _INTENT_TOKENIZER
    if _INTENT_TOKENIZER is None:
        _INTENT_TOKENIZER = AutoTokenizer.from_pretrained(model_name)
    return _INTENT_TOKENIZER


def get_local_intent_model(
    model_name: str = INTENT_MODEL_VERSION,
    max_context_length: int = INTENT_MODEL_CONTEXT_SIZE,
) -> TFDistilBertForSequenceClassification:
    global _INTENT_MODEL
    if _INTENT_MODEL is None or max_context_length != _INTENT_MODEL.max_seq_length:
        _INTENT_MODEL = TFDistilBertForSequenceClassification.from_pretrained(
            model_name
        )
        _INTENT_MODEL.max_seq_length = max_context_length
    return _INTENT_MODEL


def warm_up_intent_model() -> None:
    intent_tokenizer = get_intent_model_tokenizer()
    inputs = intent_tokenizer(
        MODEL_WARM_UP_STRING, return_tensors="tf", truncation=True, padding=True
    )
    get_local_intent_model()(inputs)


@simple_log_function_time()
def classify_intent(query: str) -> list[float]:
    tokenizer = get_intent_model_tokenizer()
    intent_model = get_local_intent_model()
    model_input = tokenizer(query, return_tensors="tf", truncation=True, padding=True)

    predictions = intent_model(model_input)[0]
    probabilities = tf.nn.softmax(predictions, axis=-1)

    class_percentages = np.round(probabilities.numpy() * 100, 2)
    return list(class_percentages.tolist()[0])


@router.post("/intent-model")
async def process_intent_request(
    intent_request: IntentRequest,
) -> IntentResponse:
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    class_percentages = classify_intent(intent_request.query)
    return IntentResponse(class_probs=class_percentages)
