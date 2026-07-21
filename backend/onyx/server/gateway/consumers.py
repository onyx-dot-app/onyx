from collections.abc import Callable

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort
from onyx.server.manage.llm.models import LLMProviderView
from onyx.tracing.flows import LLMFlow

ProviderFetcher = Callable[[Session, User, int], LLMProviderView | None]


class GatewayConsumer(BaseModel):
    """``matches`` recognizes the credential shape only; ``authorize`` raises
    for a matched-but-forbidden caller, so the error names the real reason
    instead of the generic no-consumer 403."""

    model_config = ConfigDict(frozen=True)

    name: str
    flow: LLMFlow
    matches: Callable[[Request, User], bool]
    authorize: Callable[[Request, User], None]
    fetch_provider: ProviderFetcher
    default_reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO


_CONSUMERS: list[GatewayConsumer] = []


def register_gateway_consumer(consumer: GatewayConsumer) -> None:
    if any(existing.name == consumer.name for existing in _CONSUMERS):
        return
    _CONSUMERS.append(consumer)


def resolve_gateway_consumer(request: Request, user: User) -> GatewayConsumer:
    for consumer in _CONSUMERS:
        if consumer.matches(request, user):
            consumer.authorize(request, user)
            return consumer
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "This credential is not authorized to use the Onyx LLM gateway.",
    )
