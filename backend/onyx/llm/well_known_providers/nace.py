import httpx

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.decisions.client import (
    NACE_API_BASE,
    NACE_CLIENT_HEADER,
    nace_client_header_value,
)
from onyx.llm.well_known_providers.models import NaceModel, NaceModelsResponse
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
                headers={
                    "Authorization": f"Bearer {api_key}",
                    NACE_CLIENT_HEADER: nace_client_header_value(),
                },
            )
            response.raise_for_status()
            payload = response.json()
    except UnicodeEncodeError:
        # HTTP headers are ASCII; a key with other characters cannot be valid.
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Unable to discover Nace models. Check the API key and model access.",
        ) from None
    except httpx.HTTPStatusError as error:
        upstream_status = error.response.status_code
        logger.warning("Nace model discovery returned HTTP %s", upstream_status)
        if upstream_status in (
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
            # Only 4xx/5xx are relayed; a redirect or other status is a bad gateway.
            status_code_override=(
                upstream_status if 400 <= upstream_status < 600 else None
            ),
        ) from None
    except httpx.RequestError as error:
        logger.warning("Nace model discovery failed: %s", type(error).__name__)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Unable to reach Nace model discovery. Try again later.",
        ) from None
    except ValueError as error:
        # response.json() failed: the body was not JSON.
        logger.warning("Nace model discovery failed: %s", type(error).__name__)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Nace model discovery returned an invalid catalog.",
        ) from None
    try:
        models = NaceModelsResponse.model_validate(payload).models
    except ValueError as error:
        logger.warning("Nace model discovery failed: %s", type(error).__name__)
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Nace model discovery returned an invalid catalog.",
        ) from None
    return [model for model in models if model.alias_for is None]
