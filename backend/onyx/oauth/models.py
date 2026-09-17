from typing import Generic, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class AuthorizationAttempt(BaseModel, Generic[PayloadT]):
    """One pending authorization request for an authenticated user.

    Payloads can contain identifiers, protocol context, and short-lived
    transaction secrets such as PKCE verifiers. They must not contain long-lived
    credentials or provider client secrets.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: str = Field(min_length=1, max_length=64)
    owner_id: str = Field(min_length=1, max_length=256)
    state: str = Field(pattern=r"^[A-Za-z0-9_-]{22,1024}$")
    expires_at: AwareDatetime
    payload: PayloadT
