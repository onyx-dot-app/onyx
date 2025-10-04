import httpx
from typing import Any, Dict, Optional, Tuple
from httpx_oauth.oauth2 import BaseOAuth2


class Auth0OAuth2(BaseOAuth2[Dict[str, Any]]):

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth0_domain: str,
        scopes: Optional[list[str]] = None,
        name: str = "auth0",
    ):
        if scopes is None:
            scopes = ["openid", "email", "profile"]
        
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            authorize_endpoint=f"https://{auth0_domain}/authorize",
            access_token_endpoint=f"https://{auth0_domain}/oauth/token",
            refresh_token_endpoint=f"https://{auth0_domain}/oauth/token",
            name=name,
            base_scopes=scopes,
            token_endpoint_auth_method="client_secret_post",
        )
        self.auth0_domain = auth0_domain

    async def get_id_email(self, token: str) -> Tuple[str, Optional[str]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{self.auth0_domain}/userinfo",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            
            user_id = data.get("sub")
            email = data.get("email")
            
            return str(user_id), email