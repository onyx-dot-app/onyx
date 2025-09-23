import json
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

import requests
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.configs.app_configs import OKTA_API_TOKEN
from onyx.configs.app_configs import OKTA_PROFILE_TOOL_ENABLED
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import message_to_string
from onyx.prompts.constants import GENERAL_SEP_PAT
from onyx.tools.base_tool import BaseTool
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()


OKTA_PROFILE_RESPONSE_ID = "okta_profile"

OKTA_TOOL_DESCRIPTION = """
The Okta profile tool can retrieve user profile information from Okta including:
- User ID, status, creation date
- Profile details like name, email, department, location, title, manager, and more
- Account status and activity
"""


class OIDCConfig(BaseModel):
    issuer: str
    jwks_uri: str | None = None
    userinfo_endpoint: str | None = None
    introspection_endpoint: str | None = None
    token_endpoint: str | None = None


class OktaProfileTool(BaseTool):
    _NAME = "get_okta_profile"
    _DESCRIPTION = """The Okta Profile Action allows the assistant to fetch the current \
user's information from Okta. It could include the user's name, email, phone number, \
address as well as other information like who they report to and who reports to them."""
    _DISPLAY_NAME = "Okta Profile"

    def __init__(
        self,
        access_token: str,
        client_id: str,
        client_secret: str,
        openid_config_url: str,
        okta_api_token: str,
        tool_id: int,
        request_timeout_sec: int = 15,
    ) -> None:
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.openid_config_url = openid_config_url
        self.request_timeout_sec = request_timeout_sec

        # Extract Okta org URL from OpenID config URL using URL parsing
        # OpenID config URL format: https://{org}.okta.com/.well-known/openid_configuration
        parsed_url = urlparse(self.openid_config_url)
        self.okta_org_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        self.okta_api_token = okta_api_token

        self._oidc_config: OIDCConfig | None = None

        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        return OKTA_PROFILE_TOOL_ENABLED and bool(OKTA_API_TOKEN)

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    def _load_oidc_config(self) -> OIDCConfig:
        if self._oidc_config is not None:
            return self._oidc_config

        resp = requests.get(self.openid_config_url, timeout=self.request_timeout_sec)
        resp.raise_for_status()
        data = resp.json()
        self._oidc_config = OIDCConfig(**data)
        logger.debug(f"Loaded OIDC config from {self.openid_config_url}")
        return self._oidc_config

    def _call_userinfo(self, access_token: str) -> dict[str, Any] | None:
        try:
            cfg = self._load_oidc_config()
            if not cfg.userinfo_endpoint:
                logger.info("OIDC config missing userinfo_endpoint")
                return None
            headers = {"Authorization": f"Bearer {access_token}"}
            r = requests.get(
                cfg.userinfo_endpoint, headers=headers, timeout=self.request_timeout_sec
            )
            if r.status_code == 200:
                return r.json()
            logger.info(
                f"userinfo call returned status {r.status_code}: {r.text[:200]}"
            )
            return None
        except requests.RequestException as e:
            logger.debug(f"userinfo request failed: {e}")
            return None

    def _call_introspection(self, access_token: str) -> dict[str, Any] | None:
        try:
            cfg = self._load_oidc_config()
            if not cfg.introspection_endpoint:
                logger.info("OIDC config missing introspection_endpoint")
                return None
            data = {
                "token": access_token,
                "token_type_hint": "access_token",
            }
            auth: tuple[str, str] | None = (self.client_id, self.client_secret)
            r = requests.post(
                cfg.introspection_endpoint,
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=self.request_timeout_sec,
            )
            if r.status_code == 200:
                return r.json()
            logger.info(
                f"introspection call returned status {r.status_code}: {r.text[:200]}"
            )
            return None
        except requests.RequestException as e:
            logger.debug(f"introspection request failed: {e}")
            return None

    def _call_users_api(self, uid: str) -> dict[str, Any]:
        """Call Okta Users API to fetch full user profile.

        Requires okta_org_url and okta_api_token to be set. Raises exception on any error.
        """
        if not self.okta_org_url or not self.okta_api_token:
            raise ValueError(
                "Okta org URL and API token are required for user profile lookup"
            )

        try:
            url = f"{self.okta_org_url.rstrip('/')}/api/v1/users/{uid}"
            headers = {"Authorization": f"SSWS {self.okta_api_token}"}
            r = requests.get(url, headers=headers, timeout=self.request_timeout_sec)
            if r.status_code == 200:
                return r.json()
            raise ValueError(
                f"Okta Users API call failed with status {r.status_code}: {r.text[:200]}"
            )
        except requests.RequestException as e:
            raise ValueError(f"Okta Users API request failed: {e}") from e

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        # The tool emits a single aggregated packet; pass it through as compact JSON
        profile = args[-1].response if args else {}
        return json.dumps(profile)

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        if force_run:
            return {}

        # Use LLM to determine if this tool should be called based on the query
        prompt = f"""
You are helping to determine if an Okta profile lookup tool should be called based on a user's query.

{OKTA_TOOL_DESCRIPTION}

Query: {query}

Conversation history:
{GENERAL_SEP_PAT}
{history}
{GENERAL_SEP_PAT}

Should the Okta profile tool be called for this query? Respond with only "YES" or "NO".
""".strip()
        response = llm.invoke(prompt)
        if response and "YES" in message_to_string(response).upper():
            return {}

        return None

    def run(
        self, override_kwargs: None = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        # Try to get UID from userinfo first, then fallback to introspection
        uid_candidate = None

        # Try userinfo endpoint first
        userinfo_data = self._call_userinfo(self.access_token)
        if userinfo_data and isinstance(userinfo_data, dict):
            uid_candidate = userinfo_data.get("uid")

        # Only try introspection if userinfo didn't provide a UID
        if not uid_candidate:
            introspection_data = self._call_introspection(self.access_token)
            if introspection_data and isinstance(introspection_data, dict):
                uid_candidate = introspection_data.get("uid")

        if not uid_candidate:
            raise ValueError(
                "Unable to fetch user profile from Okta. This likely means your Okta "
                "token has expired. Please logout, log back in, and try again."
            )

        # Call Users API to get full profile - this is now required
        users_api_data = self._call_users_api(uid_candidate)

        yield ToolResponse(
            id=OKTA_PROFILE_RESPONSE_ID, response=users_api_data["profile"]
        )

    def final_result(self, *args: ToolResponse) -> JSON_ro:
        # Return the single aggregated profile packet
        if not args:
            return {}
        return args[-1].response
