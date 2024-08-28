import torch
import torch.nn.functional as F
from fastapi import APIRouter
from huggingface_hub import snapshot_download  # type: ignore
from transformers import AutoTokenizer  # type: ignore
from transformers import BatchEncoding

from danswer.utils.logger import setup_logger
from model_server.constants import MODEL_WARM_UP_STRING
from model_server.danswer_torch_model import HybridClassifier
from model_server.utils import simple_log_function_time
from shared_configs.configs import INDEXING_ONLY
from shared_configs.configs import INTENT_MODEL_TAG
from shared_configs.configs import INTENT_MODEL_VERSION
from shared_configs.model_server_models import IntentRequest
from shared_configs.model_server_models import IntentResponse

logger = setup_logger()

router = APIRouter(prefix="/custom")

_INTENT_TOKENIZER: AutoTokenizer | None = None
_INTENT_MODEL: HybridClassifier | None = None


def get_intent_model_tokenizer() -> AutoTokenizer:
    global _INTENT_TOKENIZER
    if _INTENT_TOKENIZER is None:
        # The tokenizer details are not uploaded to the HF hub since it's just the
        # unmodified distilbert tokenizer.
        _INTENT_TOKENIZER = AutoTokenizer.from_pretrained("distilbert-base-uncased")
    return _INTENT_TOKENIZER


def get_local_intent_model(
    model_name_or_path: str = INTENT_MODEL_VERSION,
    tag: str = INTENT_MODEL_TAG,
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
                local_path = snapshot_download(repo_id=model_name_or_path, revision=tag)
                _INTENT_MODEL = HybridClassifier.from_pretrained(local_path)
            except Exception as e:
                logger.error(
                    f"Failed to load model even after attempted snapshot download: {e}"
                )
                raise
    return _INTENT_MODEL


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


@simple_log_function_time()
def run_inference(tokens: BatchEncoding) -> tuple[list[float], list[float]]:
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


def map_keywords(
    input_ids: torch.Tensor, tokenizer: AutoTokenizer, is_keyword: list[bool]
) -> list[str]:
    tokens = tokenizer.convert_ids_to_tokens(input_ids)

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


@router.post("/query-analysis")
async def process_analysis_request(
    intent_request: IntentRequest,
) -> IntentResponse:
    if INDEXING_ONLY:
        raise RuntimeError("Indexing model server should not call intent endpoint")

    is_keyword, keywords = run_analysis(intent_request)
    return IntentResponse(is_keyword=is_keyword, keywords=keywords)
