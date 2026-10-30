import httpx

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.well_known_providers.models import NaceModel, NaceModelsResponse

NACE_API_BASE = "https://console.nace.ai/v1"


def fetch_nace_models(api_key: str) -> list[NaceModel]:
    """Decision models the key can call, without the catalog's aliases.

    The catalog also lists aliases such as ``drex-latest`` and retired names
    that now resolve to another model. Those carry ``alias_for`` and are
    dropped so each model is offered once under its own name.
    """
    try:
        with httpx.Client(timeout=30.0, follow_redirects=False) as client:
            response = client.get(
                f"{NACE_API_BASE}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            models = NaceModelsResponse.model_validate(response.json()).models
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (
            OnyxErrorCode.UNAUTHENTICATED.status_code,
            OnyxErrorCode.UNAUTHORIZED.status_code,
        ):
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Unable to discover Nace models. Check the API key and model access.",
            ) from None
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Nace model discovery returned an upstream error. Try again later.",
            status_code_override=error.response.status_code,
        ) from None
    except httpx.RequestError:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Unable to reach Nace model discovery. Try again later.",
        ) from None
    except ValueError:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Nace model discovery returned an invalid catalog.",
        ) from None
    return [model for model in models if model.alias_for is None]
