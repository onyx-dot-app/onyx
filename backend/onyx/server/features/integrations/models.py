from pydantic import BaseModel

from onyx.oauth.models import SafeOAuthReturnPath


class IntegrationOAuthStartRequest(BaseModel):
    return_path: SafeOAuthReturnPath | None = None


class IntegrationOAuthStartResponse(BaseModel):
    authorization_url: str


class IntegrationOAuthCallbackRequest(BaseModel):
    code: str
    state: str
