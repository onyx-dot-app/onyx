"""Hook-flavored wrapper around the generic external-endpoint client.

Adds hook semantics on top of ``onyx.utils.external_endpoint``: the hook fail
strategy (HARD raises OnyxError, SOFT returns HookSoftFailed) and an
``on_result`` seam the EE executor uses to persist execution logs and
is_reachable.
"""

from collections.abc import Callable
from typing import Any
from typing import TypeVar

from pydantic import BaseModel

from onyx.db.enums import HookFailStrategy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.executor import HookSoftFailed
from onyx.utils.external_endpoint import ExternalEndpointConfig
from onyx.utils.external_endpoint import ExternalEndpointOutcome
from onyx.utils.external_endpoint import post_json_to_endpoint
from onyx.utils.logger import setup_logger

logger = setup_logger()


T = TypeVar("T", bound=BaseModel)


class HookEndpointConfig(ExternalEndpointConfig):
    """Endpoint settings plus the hook's failure policy."""

    fail_strategy: HookFailStrategy


def execute_hook_endpoint(
    *,
    config: HookEndpointConfig,
    payload: dict[str, Any],
    response_type: type[T],
    on_result: Callable[[ExternalEndpointOutcome], None] | None = None,
) -> T | HookSoftFailed:
    """Make the HTTP call, validate the response, and apply the fail strategy.

    ``on_result`` is invoked with the final outcome before the fail strategy is
    applied — the EE executor uses it to persist execution logs and
    is_reachable.

    Raises OnyxError on HARD failure. Returns HookSoftFailed on SOFT failure.
    """
    outcome, validated_model = post_json_to_endpoint(
        config=config, payload=payload, response_type=response_type
    )

    if on_result is not None:
        on_result(outcome)

    if not outcome.is_success:
        if config.fail_strategy == HookFailStrategy.HARD:
            raise OnyxError(
                OnyxErrorCode.HOOK_EXECUTION_FAILED,
                outcome.error_message or "Hook execution failed.",
            )
        logger.warning(
            "Hook execution failed (soft fail) for endpoint=%s: %s",
            config.endpoint_url,
            outcome.error_message,
        )
        return HookSoftFailed()

    if validated_model is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "validated_model is None for successful hook call "
            f"(endpoint={config.endpoint_url})",
        )
    return validated_model
