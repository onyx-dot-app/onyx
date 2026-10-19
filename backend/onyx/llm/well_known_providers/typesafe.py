import httpx
from pydantic import ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.models import (
    TypeSafeDecisionResponse,
    TypeSafeModel,
    TypeSafeModelsResponse,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call

TYPESAFE_TEST_MODEL = "jev-latest"


def check_typesafe_connection(api_key: str | None, model: str) -> None:
    if not api_key or not api_key.strip():
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR, "TypeSafe AI requires an API key"
        )
    if not model.strip():
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR, "Unsupported TypeSafe AI test model"
        )
    try:
        with traced_llm_call(
            flow=LLMFlow.PROVIDER_CONNECTION_TEST,
            model=model,
            provider="typesafe",
        ):
            with httpx.Client(timeout=30.0, follow_redirects=False) as client:
                response = client.post(
                    "https://api.typesafe.ai/v1/systemone",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "state": "The sky is blue.",
                        "questions": {
                            "connection_test": {
                                "type": "noul",
                                "instructions": "Does the text say the sky is blue?",
                            }
                        },
                    },
                )
                response.raise_for_status()
                TypeSafeDecisionResponse.model_validate(response.json())
    except httpx.HTTPStatusError as exc:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"TypeSafe AI connection test failed (HTTP {exc.response.status_code}). Check the API key and model access.",
        ) from None
    except (httpx.RequestError, ValidationError, ValueError):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "TypeSafe AI did not return a valid decision. Check connectivity and try again.",
        ) from None


def fetch_typesafe_models(api_key: str) -> list[TypeSafeModel]:
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            response = client.get(
                "https://api.typesafe.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            return TypeSafeModelsResponse.model_validate(response.json()).models
    except (httpx.HTTPError, ValueError):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Unable to discover TypeSafe AI models. Check the API key and model access.",
        ) from None
