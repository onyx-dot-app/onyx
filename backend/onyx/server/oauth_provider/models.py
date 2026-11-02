from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.auth.constants import OAUTH_PROVIDER_SECRET_PATTERN


class OAuthConsentInfo(BaseModel):
    client_name: str
    redirect_origin: str
    account_email: str
    workspace_name: str
    scopes: list[str]
    csrf_token: str = Field(repr=False)


class OAuthConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=rf"^{OAUTH_PROVIDER_SECRET_PATTERN}$")
    csrf_token: str = Field(pattern=rf"^{OAUTH_PROVIDER_SECRET_PATTERN}$", repr=False)
    decision: Literal["allow", "deny"]


class OAuthConsentResult(BaseModel):
    redirect_url: str
