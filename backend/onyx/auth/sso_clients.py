"""Hardened OIDC client for multi-IdP SSO. Two guarantees on top of the
stock client: the email claim is trusted only when the IdP marks it
verified, and the discovery document's issuer must own the configured
discovery URL, so one provider's tokens cannot be replayed against another
provider's callback (OIDC mix-up defense)."""

from typing import Any

from httpx_oauth.clients.openid import BASE_SCOPES
from httpx_oauth.clients.openid import OpenID
from httpx_oauth.exceptions import GetIdEmailError


class OpenIDConfigurationIssuerMismatch(ValueError):
    """The discovery document's issuer does not own the configured URL."""


def validate_issuer_owns_config_url(
    issuer: str | None, openid_configuration_endpoint: str
) -> None:
    """Per OIDC Discovery, the configuration document lives under the
    issuer's own URL. A document whose issuer does not prefix the configured
    endpoint is either misconfigured or an impersonation attempt."""
    if not issuer or not openid_configuration_endpoint.startswith(issuer.rstrip("/")):
        raise OpenIDConfigurationIssuerMismatch(
            f"OpenID discovery document issuer {issuer!r} does not own "
            f"the configured endpoint {openid_configuration_endpoint!r}"
        )


class VerifiedEmailOpenID(OpenID):
    """OpenID client that refuses to hand back an email the IdP has not
    verified. An absent email_verified claim counts as unverified, since a
    mutable, unverified email claim is exactly the nOAuth account-takeover
    vector. A response with no email at all is passed through unchanged and
    rejected by the login flow's existing no-email handling."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        openid_configuration_endpoint: str,
        name: str = "openid",
        base_scopes: list[str] | None = BASE_SCOPES,
    ):
        super().__init__(
            client_id,
            client_secret,
            openid_configuration_endpoint,
            name=name,
            base_scopes=base_scopes,
        )
        validate_issuer_owns_config_url(
            self.openid_configuration.get("issuer"), openid_configuration_endpoint
        )

    @property
    def expected_issuer(self) -> str:
        """The issuer this client is pinned to, for callers that validate
        tokens or store per-provider metadata."""
        return str(self.openid_configuration["issuer"])

    async def get_id_email(self, token: str) -> tuple[str, str | None]:
        async with self.get_httpx_client() as client:
            response = await client.get(
                self.openid_configuration["userinfo_endpoint"],
                headers={**self.request_headers, "Authorization": f"Bearer {token}"},
            )

            if response.status_code >= 400:
                raise GetIdEmailError(response=response)

            data: dict[str, Any] = response.json()

            email = data.get("email")
            if email is not None and data.get("email_verified") is not True:
                raise GetIdEmailError(
                    "Identity provider did not mark the email as verified",
                    response,
                )

            return str(data["sub"]), email
