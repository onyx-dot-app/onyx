import httpx

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.models import (
    TypeSafeModel,
    TypeSafeModelsResponse,
)


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
