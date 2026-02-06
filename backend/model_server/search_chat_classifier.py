from typing import Optional
from typing import TYPE_CHECKING

import torch
from fastapi import APIRouter
from fastapi import HTTPException
from huggingface_hub import snapshot_download

from onyx.utils.logger import setup_logger
from shared_configs.configs import SEARCH_CHAT_CLASSIFIER_MODEL
from shared_configs.configs import SEARCH_CHAT_CLASSIFIER_TAG
from shared_configs.model_server_models import SearchChatClassificationRequest
from shared_configs.model_server_models import SearchChatClassificationResponse

if TYPE_CHECKING:
    from transformers import PreTrainedModel
    from transformers import PreTrainedTokenizer

logger = setup_logger()

router = APIRouter(prefix="/classifier")

# Global model cache
_SEARCH_CHAT_MODEL: Optional["SearchChatClassifier"] = None


class SearchChatClassifier:
    """Wrapper for the DeBERTa-based search/chat classifier."""

    def __init__(self, model_path: str):
        # Lazy import transformers to avoid eager loading
        from transformers import AutoModelForSequenceClassification
        from transformers import AutoTokenizer

        self.tokenizer: "PreTrainedTokenizer" = AutoTokenizer.from_pretrained(
            model_path
        )
        self.model: "PreTrainedModel" = (
            AutoModelForSequenceClassification.from_pretrained(model_path)
        )

        # Move to GPU if available
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")

        self.model.to(self.device)
        self.model.eval()

        # Label mapping for nmgarza5/search-chat-classifier model
        # Based on testing: class 0 = search, class 1 = chat
        # Note: The model config uses generic LABEL_0/LABEL_1, so we override with known mapping
        self.id2label = {0: "search", 1: "chat"}
        logger.info(f"Using label mapping: {self.id2label}")

    def predict(self, query: str) -> tuple[bool, float]:
        """
        Classify a query as search or chat.

        Returns:
            tuple[bool, float]: (is_search, confidence)
        """
        with torch.no_grad():
            inputs = self.tokenizer(
                query,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            outputs = self.model(**inputs)
            logits = outputs.logits
            probabilities = torch.softmax(logits, dim=-1)

            predicted_class = torch.argmax(probabilities, dim=-1).item()
            confidence = probabilities[0][predicted_class].item()

            # Determine if it's a search query based on label mapping
            label = self.id2label.get(predicted_class, str(predicted_class))
            is_search = label.lower() == "search"

            return is_search, confidence


def get_search_chat_classifier(
    model_name: str = SEARCH_CHAT_CLASSIFIER_MODEL,
    tag: str | None = SEARCH_CHAT_CLASSIFIER_TAG,
) -> SearchChatClassifier:
    """Load or return cached search-chat classifier model."""
    global _SEARCH_CHAT_MODEL

    if _SEARCH_CHAT_MODEL is None:
        try:
            # Try loading from local cache first
            logger.notice(
                f"Loading search-chat classifier from local cache: {model_name}"
            )
            local_path = snapshot_download(
                repo_id=model_name, revision=tag, local_files_only=True
            )
            _SEARCH_CHAT_MODEL = SearchChatClassifier(local_path)
            logger.notice(
                f"Loaded search-chat classifier from local cache: {local_path}"
            )
        except Exception as e:
            logger.warning(f"Failed to load from local cache: {e}")
            try:
                # Fallback: download from HuggingFace Hub
                logger.notice(f"Downloading search-chat classifier: {model_name}")
                local_path = snapshot_download(
                    repo_id=model_name, revision=tag, local_files_only=False
                )
                _SEARCH_CHAT_MODEL = SearchChatClassifier(local_path)
                logger.notice(
                    f"Downloaded and loaded search-chat classifier: {local_path}"
                )
            except Exception as e:
                logger.error(f"Failed to load search-chat classifier: {e}")
                raise

    return _SEARCH_CHAT_MODEL


@router.post("/search-chat")
async def classify_search_chat(
    request: SearchChatClassificationRequest,
) -> SearchChatClassificationResponse:
    """
    Classify whether a query is better suited for search or chat mode.

    Returns:
        SearchChatClassificationResponse with is_search boolean and confidence score
    """
    try:
        classifier = get_search_chat_classifier()
        is_search, confidence = classifier.predict(request.query)

        logger.debug(
            f"Search-chat classification: query='{request.query[:50]}...' "
            f"is_search={is_search} confidence={confidence:.3f}"
        )

        return SearchChatClassificationResponse(
            is_search=is_search,
            confidence=confidence,
        )
    except Exception as e:
        logger.exception("Error during search-chat classification")
        raise HTTPException(
            status_code=500,
            detail=f"Error during search-chat classification: {e}",
        )
