from typing import cast
from typing import Optional
from typing import TYPE_CHECKING

import numpy as np
import torch
import torch.nn.functional as F
from fastapi import APIRouter
from huggingface_hub import snapshot_download  # type: ignore

from model_server.constants import INFORMATION_CONTENT_MODEL_WARM_UP_STRING
from model_server.constants import MODEL_WARM_UP_STRING
from model_server.onyx_torch_model import ConnectorClassifier
from model_server.onyx_torch_model import HybridClassifier
from model_server.utils import simple_log_function_time
from onyx.utils.logger import setup_logger
from shared_configs.configs import CONNECTOR_CLASSIFIER_MODEL_REPO
from shared_configs.configs import CONNECTOR_CLASSIFIER_MODEL_TAG
from shared_configs.configs import (
    INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH,
)
from shared_configs.configs import INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX
from shared_configs.configs import INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
from shared_configs.configs import (
    INDEXING_INFORMATION_CONTENT_CLASSIFICATION_TEMPERATURE,
)
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import INFORMATION_CONTENT_MODEL_TAG
from shared_configs.configs import INFORMATION_CONTENT_MODEL_VERSION
from shared_configs.configs import INTENT_MODEL_TAG
from shared_configs.configs import INTENT_MODEL_VERSION
from shared_configs.model_server_models import ConnectorClassificationRequest
from shared_configs.model_server_models import ConnectorClassificationResponse
from shared_configs.model_server_models import ContentClassificationPrediction
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse

if TYPE_CHECKING:
    from setfit import SetFitModel  # type: ignore
    from transformers import PreTrainedTokenizer, BatchEncoding  # type: ignore


logger = setup_logger()

router = APIRouter(prefix="/custom")

_CONNECTOR_CLASSIFIER_TOKENIZER: Optional["PreTrainedTokenizer"] = None
_CONNECTOR_CLASSIFIER_MODEL: ConnectorClassifier | None = None

_INTENT_TOKENIZER: Optional["PreTrainedTokenizer"] = None
_INTENT_MODEL: HybridClassifier | None = None

_INFORMATION_CONTENT_MODEL: Optional["SetFitModel"] = None

_INFORMATION_CONTENT_MODEL_PROMPT_PREFIX: str = ""  # spec to model version!


def get_connector_classifier_tokenizer() -> "PreTrainedTokenizer":
    global _CONNECTOR_CLASSIFIER_TOKENIZER
    from transformers import AutoTokenizer, PreTrainedTokenizer

    if _CONNECTOR_CLASSIFIER_TOKENIZER is None:
        # The tokenizer details are not uploaded to the HF hub since it's just the
        # unmodified distilbert tokenizer.
        _CONNECTOR_CLASSIFIER_TOKENIZER = cast(
            PreTrainedTokenizer,
            AutoTokenizer.from_pretrained("distilbert-base-uncased"),
        )
    return _CONNECTOR_CLASSIFIER_TOKENIZER


def get_local_connector_classifier(
    model_name_or_path: str = CONNECTOR_CLASSIFIER_MODEL_REPO,
    tag: str = CONNECTOR_CLASSIFIER_MODEL_TAG,
) -> ConnectorClassifier:
    global _CONNECTOR_CLASSIFIER_MODEL
    if _CONNECTOR_CLASSIFIER_MODEL is None:
        try:
            # Calculate where the cache should be, then load from local if available
            local_path = snapshot_download(
                repo_id=model_name_or_path, revision=tag, local_files_only=True
            )
            _CONNECTOR_CLASSIFIER_MODEL = ConnectorClassifier.from_pretrained(
                local_path
            )
        except Exception as e:
            logger.warning(f"Failed to load model directly: {e}")
            try:
                # Attempt to download the model snapshot
                logger.info(f"Downloading model snapshot for {model_name_or_path}")
                local_path = snapshot_download(repo_id=model_name_or_path, revision=tag)
                _CONNECTOR_CLASSIFIER_MODEL = ConnectorClassifier.from_pretrained(
                    local_path
                )
            except Exception as e:
                logger.error(
                    f"Failed to load model even after attempted snapshot download: {e}"
                )
                raise
    return _CONNECTOR_CLASSIFIER_MODEL


def get_intent_model_tokenizer() -> "PreTrainedTokenizer":
    from transformers import AutoTokenizer, PreTrainedTokenizer

    global _INTENT_TOKENIZER
    if _INTENT_TOKENIZER is None:
        # The tokenizer details are not uploaded to the HF hub since it's just the
        # unmodified distilbert tokenizer.
        _INTENT_TOKENIZER = cast(
            PreTrainedTokenizer,
            AutoTokenizer.from_pretrained("distilbert-base-uncased"),
        )
    return _INTENT_TOKENIZER


def get_local_intent_model(
    model_name_or_path: str = INTENT_MODEL_VERSION,
    tag: str | None = INTENT_MODEL_TAG,
) -> HybridClassifier:
    global _INTENT_MODEL
    if _INTENT_MODEL is None:
        try:
            # Calculate where the cache should be, then load from local if available
            logger.notice(f"Loading model from local cache: {model_name_or_path}")
            local_path = snapshot_download(
                repo_id=model_name_or_path, revision=tag, local_files_only=True
            )
            _INTENT_MODEL = HybridClassifier.from_pretrained(local_path)
            logger.notice(f"Loaded model from local cache: {local_path}")
        except Exception as e:
            logger.warning(f"Failed to load model directly: {e}")
            try:
                # Attempt to download the model snapshot
                logger.notice(f"Downloading model snapshot for {model_name_or_path}")
                local_path = snapshot_download(
                    repo_id=model_name_or_path, revision=tag, local_files_only=False
                )
                _INTENT_MODEL = HybridClassifier.from_pretrained(local_path)
            except Exception as e:
                logger.error(
                    f"Failed to load model even after attempted snapshot download: {e}"
                )
                raise
    return _INTENT_MODEL


def get_local_information_content_model(
    model_name_or_path: str = INFORMATION_CONTENT_MODEL_VERSION,
    tag: str | None = INFORMATION_CONTENT_MODEL_TAG,
) -> "SetFitModel":
    from setfit import SetFitModel

    global _INFORMATION_CONTENT_MODEL
    if _INFORMATION_CONTENT_MODEL is None:
        try:
            # Calculate where the cache should be, then load from local if available
            logger.notice(
                f"Loading content information model from local cache: {model_name_or_path}"
            )
            local_path = snapshot_download(
                repo_id=model_name_or_path, revision=tag, local_files_only=True
            )
            _INFORMATION_CONTENT_MODEL = SetFitModel.from_pretrained(local_path)
            logger.notice(
                f"Loaded content information model from local cache: {local_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to load content information model directly: {e}")
            try:
                # Attempt to download the model snapshot
                logger.notice(
                    f"Downloading content information model snapshot for {model_name_or_path}"
                )
                local_path = snapshot_download(
                    repo_id=model_name_or_path, revision=tag, local_files_only=False
                )
                _INFORMATION_CONTENT_MODEL = SetFitModel.from_pretrained(local_path)
            except Exception as e:
                logger.error(
                    f"Failed to load content information model even after attempted snapshot download: {e}"
                )
                raise

    return _INFORMATION_CONTENT_MODEL


def tokenize_connector_classification_query(
    connectors: list[str],
    query: str,
    tokenizer: "PreTrainedTokenizer",
    connector_token_end_id: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Tokenize the connectors & user query into one prompt for the forward pass of ConnectorClassifier models

    The attention mask is just all 1s. The prompt is CLS + each connector name suffixed with the connector end
    token and then the user query.
    """

    input_ids = torch.tensor([tokenizer.cls_token_id], dtype=torch.long)

    for connector in connectors:
        connector_token_ids = tokenizer(
            connector,
            add_special_tokens=False,
            return_tensors="pt",
        )

        input_ids = torch.cat(
            (
                input_ids,
                connector_token_ids["input_ids"].squeeze(dim=0),
                torch.tensor([connector_token_end_id], dtype=torch.long),
            ),
            dim=-1,
        )
    query_token_ids = tokenizer(
        query,
        add_special_tokens=False,
        return_tensors="pt",
    )

    input_ids = torch.cat(
        (
            input_ids,
            query_token_ids["input_ids"].squeeze(dim=0),
            torch.tensor([tokenizer.sep_token_id], dtype=torch.long),
        ),
        dim=-1,
    )
    attention_mask = torch.ones(input_ids.numel(), dtype=torch.long)

    return input_ids.unsqueeze(0), attention_mask.unsqueeze(0)


def warm_up_connector_classifier_model() -> None:
    logger.info(
        f"Warming up connector_classifier model {CONNECTOR_CLASSIFIER_MODEL_TAG}"
    )
    connector_classifier_tokenizer = get_connector_classifier_tokenizer()
    connector_classifier = get_local_connector_classifier()

    input_ids, attention_mask = tokenize_connector_classification_query(
        ["GitHub"],
        "onyx classifier query google doc",
        connector_classifier_tokenizer,
        connector_classifier.connector_end_token_id,
    )
    input_ids = input_ids.to(connector_classifier.device)
    attention_mask = attention_mask.to(connector_classifier.device)

    connector_classifier(input_ids, attention_mask)


def warm_up_intent_model() -> None:
    logger.notice(f"Warming up Intent Model: {INTENT_MODEL_VERSION}")
    intent_tokenizer = get_intent_model_tokenizer()
    tokens = intent_tokenizer(
        MODEL_WARM_UP_STRING, return_tensors="pt", truncation=True, padding=True
    )

    intent_model = get_local_intent_model()
    device = intent_model.device
    intent_model(
        query_ids=tokens["input_ids"].to(device),
        query_mask=tokens["attention_mask"].to(device),
    )


def warm_up_information_content_model() -> None:
    logger.notice("Warming up Content Model")  # TODO: add version if needed

    information_content_model = get_local_information_content_model()
    information_content_model(INFORMATION_CONTENT_MODEL_WARM_UP_STRING)


@simple_log_function_time()
def run_inference(tokens: "BatchEncoding") -> tuple[list[float], list[float]]:
    intent_model = get_local_intent_model()
    device = intent_model.device

    outputs = intent_model(
        query_ids=tokens["input_ids"].to(device),
        query_mask=tokens["attention_mask"].to(device),
    )

    token_logits = outputs["token_logits"]
    intent_logits = outputs["intent_logits"]

    # Move tensors to CPU before applying softmax and converting to numpy
    intent_probabilities = F.softmax(intent_logits.cpu(), dim=-1).numpy()[0]
    token_probabilities = F.softmax(token_logits.cpu(), dim=-1).numpy()[0]

    # Extract the probabilities for the positive class (index 1) for each token
    token_positive_probs = token_probabilities[:, 1].tolist()

    return intent_probabilities.tolist(), token_positive_probs


@simple_log_function_time()
def run_content_classification_inference(
    text_inputs: list[str],
) -> list[ContentClassificationPrediction]:
    """
    Assign a score to the segments in question. The model stored in get_local_information_content_model()
    creates the 'model score' based on its training, and the scores are then converted to a 0.0-1.0 scale.
    In the code outside of the model/inference model servers that score will be converted into the actual
    boost factor.
    """

    def _prob_to_score(prob: float) -> float:
        """
        Conversion of base score to 0.0 - 1.0 score. Note that the min/max values depend on the model!
        """
        _MIN_BASE_SCORE = 0.25
        _MAX_BASE_SCORE = 0.75
        if prob < _MIN_BASE_SCORE:
            raw_score = 0.0
        elif prob < _MAX_BASE_SCORE:
            raw_score = (prob - _MIN_BASE_SCORE) / (_MAX_BASE_SCORE - _MIN_BASE_SCORE)
        else:
            raw_score = 1.0
        return (
            INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
            + (
                INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX
                - INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
            )
            * raw_score
        )

    _BATCH_SIZE = 32
    content_model = get_local_information_content_model()

    # Process inputs in batches
    all_output_classes: list[int] = []
    all_base_output_probabilities: list[float] = []

    for i in range(0, len(text_inputs), _BATCH_SIZE):
        batch = text_inputs[i : i + _BATCH_SIZE]
        batch_with_prefix = []
        batch_indices = []

        # Pre-allocate results for this batch
        batch_output_classes: list[np.ndarray] = [np.array(1)] * len(batch)
        batch_probabilities: list[np.ndarray] = [np.array(1.0)] * len(batch)

        # Pre-process batch to handle long input exceptions
        for j, text in enumerate(batch):
            if len(text) == 0:
                # if no input, treat as non-informative from the model's perspective
                batch_output_classes[j] = np.array(0)
                batch_probabilities[j] = np.array(0.0)
                logger.warning("Input for Content Information Model is empty")

            elif (
                len(text.split())
                <= INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH
            ):
                # if input is short, use the model
                batch_with_prefix.append(
                    _INFORMATION_CONTENT_MODEL_PROMPT_PREFIX + text
                )
                batch_indices.append(j)
            else:
                # if longer than cutoff, treat as informative (stay with default), but issue warning
                logger.warning("Input for Content Information Model too long")

        if batch_with_prefix:  # Only run model if we have valid inputs
            # Get predictions for the batch
            model_output_classes = content_model(batch_with_prefix)
            model_output_probabilities = content_model.predict_proba(batch_with_prefix)

            # Place results in the correct positions
            for idx, batch_idx in enumerate(batch_indices):
                batch_output_classes[batch_idx] = model_output_classes[idx].numpy()
                batch_probabilities[batch_idx] = model_output_probabilities[idx][
                    1
                ].numpy()  # x[1] is prob of the positive class

        all_output_classes.extend([int(x) for x in batch_output_classes])
        all_base_output_probabilities.extend([float(x) for x in batch_probabilities])

    logits = [
        np.log(p / (1 - p)) if p != 0.0 and p != 1.0 else (100 if p == 1.0 else -100)
        for p in all_base_output_probabilities
    ]
    scaled_logits = [
        logit / INDEXING_INFORMATION_CONTENT_CLASSIFICATION_TEMPERATURE
        for logit in logits
    ]
    output_probabilities_with_temp = [
        np.exp(scaled_logit) / (1 + np.exp(scaled_logit))
        for scaled_logit in scaled_logits
    ]

    prediction_scores = [
        _prob_to_score(p_temp) for p_temp in output_probabilities_with_temp
    ]

    content_classification_predictions = [
        ContentClassificationPrediction(
            predicted_label=predicted_label, content_boost_factor=output_score
        )
        for predicted_label, output_score in zip(all_output_classes, prediction_scores)
    ]

    return content_classification_predictions


def map_keywords(
    input_ids: torch.Tensor, tokenizer: "PreTrainedTokenizer", is_keyword: list[bool]
) -> list[str]:
    tokens = tokenizer.convert_ids_to_tokens(input_ids)  # type: ignore

    if not len(tokens) == len(is_keyword):
        raise ValueError("Length of tokens and keyword predictions must match")

    if input_ids[0] == tokenizer.cls_token_id:
        tokens = tokens[1:]
        is_keyword = is_keyword[1:]

    if input_ids[-1] == tokenizer.sep_token_id:
        tokens = tokens[:-1]
        is_keyword = is_keyword[:-1]

    unk_token = tokenizer.unk_token
    if unk_token in tokens:
        raise ValueError("Unknown token detected in the input")

    keywords = []
    current_keyword = ""

    for ind, token in enumerate(tokens):
        if is_keyword[ind]:
            if token.startswith("##"):
                current_keyword += token[2:]
            else:
                if current_keyword:
                    keywords.append(current_keyword)
                current_keyword = token
        else:
            # If mispredicted a later token of a keyword, add it to the current keyword
            # to complete it
            if current_keyword:
                if len(current_keyword) > 2 and current_keyword.startswith("##"):
                    current_keyword = current_keyword[2:]

                else:
                    keywords.append(current_keyword)
                    current_keyword = ""

    if current_keyword:
        keywords.append(current_keyword)

    return keywords


def clean_keywords(keywords: list[str]) -> list[str]:
    cleaned_words = []
    for word in keywords:
        word = word[:-2] if word.endswith("'s") else word
        word = word.replace("/", " ")
        word = word.replace("'", "").replace('"', "")
        cleaned_words.extend([w for w in word.strip().split() if w and not w.isspace()])
    return cleaned_words


def run_connector_classification(req: ConnectorClassificationRequest) -> list[str]:
    tokenizer = get_connector_classifier_tokenizer()
    model = get_local_connector_classifier()

    connector_names = req.available_connectors

    input_ids, attention_mask = tokenize_connector_classification_query(
        connector_names,
        req.query,
        tokenizer,
        model.connector_end_token_id,
    )
    input_ids = input_ids.to(model.device)
    attention_mask = attention_mask.to(model.device)

    global_confidence, classifier_confidence = model(input_ids, attention_mask)

    if global_confidence.item() < 0.5:
        return []

    passed_connectors = []

    for i, connector_name in enumerate(connector_names):
        if classifier_confidence.view(-1)[i].item() > 0.5:
            passed_connectors.append(connector_name)

    return passed_connectors


def run_analysis(intent_req: IntentRequest) -> tuple[bool, list[str]]:
    tokenizer = get_intent_model_tokenizer()
    model_input = tokenizer(
        intent_req.query, return_tensors="pt", truncation=False, padding=False
    )

    if len(model_input.input_ids[0]) > 512:
        # If the user text is too long, assume it is semantic and keep all words
        return True, intent_req.query.split()

    intent_probs, token_probs = run_inference(model_input)

    is_keyword_sequence = intent_probs[0] >= intent_req.keyword_percent_threshold

    keyword_preds = [
        token_prob >= intent_req.keyword_percent_threshold for token_prob in token_probs
    ]

    try:
        keywords = map_keywords(model_input.input_ids[0], tokenizer, keyword_preds)
    except Exception as e:
        logger.error(
            f"Failed to extract keywords for query: {intent_req.query} due to {e}"
        )
        # Fallback to keeping all words
        keywords = intent_req.query.split()

    cleaned_keywords = clean_keywords(keywords)

    return is_keyword_sequence, cleaned_keywords


@router.post("/connector-classification")
async def process_connector_classification_request(
    classification_request: ConnectorClassificationRequest,
) -> ConnectorClassificationResponse:
    if INDEXING_ONLY:
        raise RuntimeError(
            "Indexing model server should not call connector classification endpoint"
        )

    if len(classification_request.available_connectors) == 0:
        return ConnectorClassificationResponse(connectors=[])

    connectors = run_connector_classification(classification_request)
    return ConnectorClassificationResponse(connectors=connectors)


@router.post("/query-analysis")
async def process_analysis_request(
    intent_request: IntentRequest,
) -> IntentResponse:
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    is_keyword, keywords = run_analysis(intent_request)
    return IntentResponse(is_keyword=is_keyword, keywords=keywords)


@router.post("/content-classification")
async def process_content_classification_request(
    content_classification_requests: list[str],
) -> list[ContentClassificationPrediction]:
    return run_content_classification_inference(content_classification_requests)
