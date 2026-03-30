from typing import Any
from typing import cast
from urllib.parse import urlencode

from onyx.configs.app_configs import FEISHU_CLIENT_ID
from onyx.configs.app_configs import FEISHU_CLIENT_SECRET
from onyx.configs.app_configs import FEISHU_OAUTH_SCOPE
from onyx.configs.app_configs import FEISHU_REDIRECT_URI
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
)
from onyx.connectors.interfaces import OAuthConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.utils.retry_wrapper import request_with_retries

_FEISHU_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
_FEISHU_USERINFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"


def _unwrap_feishu_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


class FeishuConnector(OAuthConnector):
    def __init__(self) -> None:
        self.access_token: str | None = None
        self.user_info: dict[str, Any] | None = None

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.FEISHU

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
    ) -> str:
        del additional_kwargs

        if not FEISHU_CLIENT_ID:
            raise ValueError("FEISHU_CLIENT_ID environment variable must be set")

        redirect_uri = FEISHU_REDIRECT_URI or get_oauth_callback_uri(
            base_domain, DocumentSource.FEISHU.value
        )
        query = urlencode(
            {
                "client_id": FEISHU_CLIENT_ID,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": FEISHU_OAUTH_SCOPE,
                "state": state,
            }
        )
        return f"{_FEISHU_AUTHORIZE_URL}?{query}"

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],
    ) -> dict[str, Any]:
        del additional_kwargs

        if not FEISHU_CLIENT_ID:
            raise ValueError("FEISHU_CLIENT_ID environment variable must be set")
        if not FEISHU_CLIENT_SECRET:
            raise ValueError("FEISHU_CLIENT_SECRET environment variable must be set")

        redirect_uri = FEISHU_REDIRECT_URI or get_oauth_callback_uri(
            base_domain, DocumentSource.FEISHU.value
        )
        token_response = request_with_retries(
            method="POST",
            url=_FEISHU_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": FEISHU_CLIENT_ID,
                "client_secret": FEISHU_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            backoff=0,
            delay=0.1,
        )
        token_payload = _unwrap_feishu_payload(token_response.json())
        access_token = token_payload.get("access_token")
        if not access_token:
            raise RuntimeError(
                f"Failed to exchange code for Feishu access token: {token_response.text}"
            )

        userinfo_response = request_with_retries(
            method="GET",
            url=_FEISHU_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            backoff=0,
            delay=0.1,
        )
        userinfo_payload = _unwrap_feishu_payload(userinfo_response.json())

        token_data = dict(token_payload)
        token_data["access_token"] = access_token
        token_data["token_type"] = token_payload.get("token_type", "Bearer")

        for key in [
            "open_id",
            "union_id",
            "name",
            "en_name",
            "email",
            "avatar_url",
            "avatar_thumb",
            "avatar_middle",
            "avatar_big",
        ]:
            value = userinfo_payload.get(key)
            if value:
                token_data[key] = value

        token_data["user_info"] = userinfo_payload
        return token_data

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        access_token = credentials.get("access_token")
        if not access_token:
            raise ConnectorMissingCredentialError("Feishu")

        self.access_token = cast(str, access_token)
        user_info = credentials.get("user_info")
        self.user_info = user_info if isinstance(user_info, dict) else None
        return None

    def validate_connector_settings(self) -> None:
        if not self.access_token:
            raise ConnectorMissingCredentialError("Feishu")

        response = request_with_retries(
            method="GET",
            url=_FEISHU_USERINFO_URL,
            headers={"Authorization": f"Bearer {self.access_token}"},
            backoff=0,
            delay=0.1,
        )
        self.user_info = _unwrap_feishu_payload(response.json())
