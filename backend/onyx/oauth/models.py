from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field

from onyx.utils.url import sanitize_next_url

PayloadT = TypeVar("PayloadT", bound=BaseModel)


def _validate_safe_oauth_return_path(value: str) -> str:
    if sanitize_next_url(value) != value or any(
        not character.isprintable() for character in value
    ):
        raise ValueError("OAuth return path must be a safe internal path")
    return value


SafeOAuthReturnPath = Annotated[
    str,
    Field(max_length=2048),
    AfterValidator(_validate_safe_oauth_return_path),
]
OAuthConfigurationFingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PKCECodeVerifier = Annotated[str, Field(min_length=43, max_length=128)]


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
